# C2 — Auth, Identity & Access Control

## 1. Authentication (Clerk)
- Sign-up/login via Clerk components; allow-list corporate email domains and/or invitation-only; MFA enforced; SAML/OIDC SSO via Clerk enterprise connections if the company has an IdP.
- Browser holds the Clerk session; API calls carry a short-lived **JWT** (`Authorization: Bearer`). Use a Clerk **JWT template** adding `org_id`, `org_role`, and `email`.
- **API verification**: validate signature via Clerk JWKS (cached, rotated), `iss`, `aud`/`azp`, `exp`, `nbf`; reject otherwise. No session lookups on the hot path.
- **User provisioning**: Clerk webhook (`user.created/updated/deleted`, `organizationMembership.*`) → `/v1/webhooks/clerk` (Svix signature verified, idempotent by event id) → upsert `users`, `group_members`. Fallback: lazy-create on first authenticated request.
- Deletion/offboarding: `user.deleted` → soft-disable immediately, async purge of personal docs, datasets, chats per retention policy; audit entry.

## 2. Authorization model

| Layer | Mechanism |
|-------|-----------|
| Role (coarse) | `member`, `knowledge_admin`, `data_admin`, `admin` (RBAC on API routes) |
| Group (fine) | Groups mapped from Clerk org roles / IdP groups (e.g., `finance`, `hr`, `eng`) |
| Document | `scope=personal` → owner only; `scope=enterprise` → `document_acl` groups (empty = all employees) |
| Data source/table | `source_grants` (group → source, optional table allow-list, optional row-filter predicate) |
| Dataset (CSV) | Owner only (v1); sharing later |
| Artifact/chat | Owner only |

**Principle: authorization is enforced below the LLM.** The model never decides access. The server builds an immutable `UserContext{user_id, org_id, role, group_ids, allowed_source_ids}` per request, passes it to every tool by closure (not via prompt), and every tool re-checks.

### Enforcement points
1. **API** — route RBAC + ownership checks (`chat.user_id == ctx.user_id`).
2. **Retrieval** — mandatory ACL predicate built from `UserContext` (never from request params); RLS as backstop.
3. **Catalog retrieval** — only tables the user's groups can see are even offered to the SQL agent (so the model can't reference the rest).
4. **SQL validation** — AST allow-list of tables/columns from the user's grants; row-filter predicates injected by the gateway.
5. **Data Gateway** — re-validates and uses per-source read-only DB roles; optional per-group DB roles / session variables for DB-native RLS.
6. **Sandbox** — Phase 1: only the run's datasets are copied into the isolated temp dir (no object-store credentials inside); Phase 2: STS session policy limits the S3 prefix to the user's artifacts/datasets for this run.
7. **Audit** — all of the above logged (`audit_log`, `sql_query_log`).

## 3. Sensitive data handling
- Column-level `pii`/`sensitivity` flags in the catalog: restricted columns excluded from the LLM-visible schema unless group is granted; PII columns masked in samples and in rows sent to the LLM when policy says "mask".
- Only **aggregated or capped samples** (≤ 50 rows) of query results go to the model; full results stay in artifacts (S3) and render to the user directly.
- Enterprise doc visibility changes (ACL edit) trigger an async re-stamp of `document_chunks.acl_group_ids`; until finished, retrieval uses the intersection (fail closed).

## 4. Session & token hygiene
- Short JWT lifetime (Clerk default 60 s refresh); SSE connection authenticated once at open; max SSE lifetime 30 min then client reconnects with fresh token (server rejects expired stream tokens on resume).
- CSRF: API uses bearer tokens only (no cookie auth) → no CSRF surface; CORS locked to the web origin.
- Rate limits: per user (60 req/min, 2 concurrent runs), per IP (Nginx Phase 1; WAF Phase 2), per org (LLM provider token bucket in `LLMGateway`).

## 5. Admin & break-glass
Admin routes require `role=admin` + recent MFA claim. All admin actions audited. Kill switches (disable SQL, analysis, uploads, or whole chat) via feature flags — env/Redis flag (Phase 1), AWS AppConfig (Phase 2) — with ≤ 1 min propagation.

## 6. Open questions
- Which IdP groups should map to EagleEye groups (needs the corporate directory design)?
- Do some enterprise DBs require per-user (not per-group) data entitlements (e.g., regional managers see only their region)? If so we use `row_filter_sql` templates with user attributes (e.g., `region = :user.region`) populated from Clerk metadata.
