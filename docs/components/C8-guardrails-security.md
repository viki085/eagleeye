# C8 — Guardrails & Security

## 1. Threat model (STRIDE-oriented, top risks)
| # | Threat | Vector | Primary controls |
|---|--------|--------|------------------|
| T1 | Cross-user / cross-ACL data leakage | Retrieval filters bug, cache sharing, citations | ACL below LLM, RLS backstop, scope-hash cache keys, leak test suite |
| T2 | Prompt injection (direct) | User message | Guard, input sanitiser, instruction hierarchy |
| T3 | Indirect injection | Uploaded doc / DB cell / CSV content | `<tool_data>` isolation, no write tools, guardrails on output, tool allow-list |
| T4 | SQL abuse (exfil, DoS, writes) | Generated/manipulated SQL | AST validation ×2, read-only creds, replica, timeouts, row caps |
| T5 | Sandbox escape / abuse | Generated Python | Phase 1: Docker subprocess `--network none`, isolated temp dir, AST allow-list, limits; Phase 2: Lambda isolation, STS session policy |
| T6 | Sensitive data to LLM | Rows/chunks with PII sent to model | Masking, sampling ≤ 50 rows; LLM provider enterprise ToS (no training on API data — verify at contract time per provider) |
| T7 | Malicious file upload | Malware, zip bombs, macro docs | Phase 1: MIME/magic-byte check, type/size allow-list, parsers in isolated workers, no macro execution; Phase 2: GuardDuty Malware Protection for S3 |
| T8 | Account takeover / token theft | Stolen JWT | Short JWT, MFA, CSP, httpOnly Clerk session, anomaly alerts |
| T9 | Cost / DoS abuse | Prompt floods, long loops | Rate limits, budgets, WAF, quotas, kill switch |
| T10 | Supply chain | Dependencies, container images | Pinned deps, SCA (Dependabot/Trivy), SBOM, ECR scan, signed images |
| T11 | Insider / admin misuse | Broad admin rights | RBAC, MFA, audit log immutability, break-glass flow |

## 2. Guardrail layers (defence in depth)
1. **Edge**: WAF managed rules, bot control, IP rate limits, size limits.
2. **Input**: regex sanitiser → Guard LLM classification → configurable guardrail rules (prompt-attack patterns, denied-topic list, PII anonymise/block). Fail closed.
3. **Instruction hierarchy**: system rules override user text; tool outputs are data; documents/rows can't change tool permissions or reveal prompts.
4. **Tool boundary**: typed schemas, allow-listed tools, argument validation, per-tool timeouts, per-user rate limits, read-only everywhere.
5. **Data boundary**: ACL filters, catalog grants, gateway re-validation, masking, sandbox network isolation.
6. **Output**: guardrail rules (PII regex, harmful-content patterns), secret regex (AKIA…, private keys, JWTs), system prompt leak check, grounding checks (numbers, citations), markdown sanitiser.
7. **Monitoring**: security event stream (blocked inputs, rejected SQL, ACL denials, sandbox violations) → Grafana alerts (Phase 1) / CloudWatch alarms (Phase 2) + weekly review; canary prompts in prod synthetic tests.

Design rule: **do not tell the attacker what was detected** (neutral replies); log the full input for review.

## 3. Infrastructure security

**Phase 1 (local / Docker Compose):**
- Network isolation: Docker internal network; data-gateway and Qdrant not routed through Nginx; services communicate by service name only. `--network none` on sandbox subprocess.
- Secrets: `.env` file (gitignored); `.env.example` documents every variable with no real values; startup validation fails fast on missing secrets. Never commit secrets.
- TLS: not required for localhost; Nginx handles HTTPS termination if exposed beyond localhost.
- Logging: structured JSON to Docker log driver; app logs PII-redacted; no Object Lock (dev/demo data only).
- Access control: single-machine; file permissions on volumes; Supabase RLS enforced at DB layer.

**Phase 2 (cloud / AWS):**
- VPC: private subnets for compute, isolated subnets for data, no public IPs; VPC endpoints (S3, Secrets, KMS, ECR, Logs, STS); security groups least-privilege (web→api→workers→data); NACL baseline.
- IAM: one task role per service (least privilege), no long-lived keys, SCPs on org, permission boundaries.
- Encryption: KMS CMKs (per data class) for Supabase/S3/Redis; TLS 1.2+ everywhere; Redis in-transit + AUTH/ACL.
- Secrets: AWS Secrets Manager with rotation; no secrets in env files, images, or logs; startup validation.
- Logging: CloudTrail (org), VPC Flow Logs, ALB/WAF logs → S3 with Object Lock (1-yr immutable audit); app logs structured JSON with PII redaction.
- Detection: GuardDuty, Security Hub, Config rules, Macie on S3 buckets (docs/data), Inspector for ECR/ECS.
- Backups & DR: Supabase PITR, S3 versioning + CRR; quarterly restore drill.

## 4. Application security checklist (pre-commit/CI gates)
- No hardcoded secrets (gitleaks in CI); dependency & container scans (fail on High+); SAST (Semgrep/Bandit, ESLint security).
- All inputs validated with pydantic/zod schemas at boundaries; parameterised SQL only; output encoding in UI; CSP; CORS allow-list.
- Rate limiting on every endpoint; error messages sanitised (request_id only); idempotency keys on mutating calls.
- AuthN/Z tests per route; ACL leak tests; injection and SQL-escape corpora as regression suites.
- Threat-model review at each phase gate; external penetration test before go-live.

## 5. Compliance & privacy
Data residency by region choice (D5); data processing agreement with Clerk (identity data) reviewed; LLM provider enterprise ToS (Anthropic, OpenAI, and similar providers do not use API data for training — verify current terms at contract time per provider); retention + deletion workflows (C7 §7); audit trail for access to enterprise data; DPIA if GDPR applies.

## 6. Incident response (outline)
Severity matrix; kill switches (env/Redis flags Phase 1; AppConfig Phase 2) for SQL, analysis, uploads, whole chat; revoke Clerk sessions; rotate secrets runbook; forensic trail via trace_id ↔ audit_log ↔ sql_query_log; post-mortem template.
