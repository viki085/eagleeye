# Security Review — Phase 6 (local build)

**Date:** 2026-11-13 · **Scope:** the whole local stack at the end of Phase 6 (API, web app, agent
and ingest workers, data gateway, analysis sandbox image, git history).
**Not in scope:** cloud infrastructure (Phase 2 / AWS) and an external penetration test (before
go-live, see §6).

## 1. Summary

| Area | Result |
|---|---|
| Python dependencies (`pip-audit`, full lock) | **No known vulnerabilities** |
| npm production dependencies (`npm audit --omit=dev`) | **0** (was 1 critical, 2 high, 2 moderate) |
| npm dev-only tooling | 2 critical + 7 moderate remain — need major upgrades (§4) |
| Secrets in git history (`gitleaks`, 14 commits) | **None** — 1 test fixture allow-listed |
| Sandbox image (`trivy`, HIGH/CRITICAL) | **0 critical, 0 fixable**; 47 high with no Debian fix yet (§4) |
| Static analysis (`bandit`, medium+) | 44 findings triaged: 1 fixed, 43 false positives / justified |
| Authorisation matrix | 37 routes: every non-public route needs a token; every admin route refuses members |
| Cross-user document leak | No leak through any retrieval or listing path |
| Indirect prompt injection | Contained for documents, CSV cells and DB rows; one gap found and fixed |

## 2. Threat model revisited (C8 §1)

| ID | Threat | Phase 6 status |
|---|---|---|
| T1 | Cross-user data leakage | One access predicate re-applied at hydration; new integration test proves personal docs never reach another user (keyword, vector, hydrate, pinned doc ids, list, open, source passage) |
| T2 | Direct prompt injection | Guard rules + LLM guard, fail closed (Phase 3); unchanged |
| T3 | Indirect injection | `<tool_data>` isolation; **neutraliser hardened** against look-alike brackets (`＜/tool_data＞`) and HTML-escaped tags; unknown tool calls refused; tool set fixed per run (tests + live spot checks) |
| T4 | SQL abuse | sqlsafe AST validation ×2, read-only creds (Phase 4); unchanged |
| T5 | Sandbox escape | Container flags unchanged; image now applies Debian security updates at build |
| T6 | Sensitive data to LLM | Masking/sampling (Phase 4–5); unchanged |
| T7 | Malicious upload | Magic-byte sniffing, size limits; **CSV headers proven unable to inject SQL** (test) |
| T8 | Account takeover | Custom sign-in on Clerk; **no self-signup** — the API refuses Clerk accounts it did not provision; deleted users lose access immediately (cache dropped); CSP tightened |
| T9 | Cost / DoS abuse | Rate limits, stream caps, kill switches, LLM circuit breaker (6A) |
| T10 | Supply chain | This review: SCA, secret scan, image scan; npm overrides pin patched transitive deps |
| T11 | Admin misuse | Admin role re-read from the DB per call; every admin action audited **before** it takes effect (switches, user add/delete, enterprise document add/delete); last-admin and self-delete guards |

## 3. Findings and fixes

| # | Severity | Finding | Fix |
|---|---|---|---|
| F1 | Critical (prod dep) | Next.js 15.5.9 — middleware/proxy bypass advisories | Upgraded to **15.5.29** (same major) |
| F2 | High (prod dep) | postcss ≤ 8.5.22 bundled inside Next (XSS in stringify, source-map file read) | npm `overrides` → **postcss 8.5.32** (same major; Next unchanged) |
| F3 | High (prod dep) | sharp ≤ 0.35.5-rc.1 (libvips/libheif/librsvg CVEs) | Override → **sharp 0.35.5** (a range Next 15.5.29 declares) |
| F4 | Moderate (prod dep) | postcss-selector-parser < 6.1.5 (quadratic parsing) | Override → **6.1.6** (same major; avoids npm's breaking typography downgrade) |
| F5 | High (image) | zlib heap overflows in the sandbox base image | Dockerfile now runs `apt-get upgrade`; rebuilt |
| F6 | Medium | Indirect injection: `neutralise()` matched ASCII `<` only; `＜/tool_data＞` and `&lt;/tool_data&gt;` passed through | Neutraliser covers look-alike brackets and HTML entities; 26 injection tests |
| F7 | Medium | Local object-store secret hard-coded as a default (`S105`) | Still the local default, but settings **refuse to load** outside `APP_ENV=local` while the local keys are in use |
| F8 | Low | Invisible bidi/zero-width characters in a regex source (`B613`, "trojan source") | Written as `\u` escapes; behaviour identical |

## 4. Accepted risks (with reason)

| Item | Why accepted | Revisit |
|---|---|---|
| Vitest 3.x — 2 critical (`tinypool`, Vitest UI/mocker), dev only | Runs only on developer machines during tests; we never start the Vitest UI server; fix requires Vitest 5 (major) | Upgrade Vitest with the next test-tooling refresh |
| `@typescript-eslint` via `minimatch` — 7 moderate, dev only | Lint-time only, input is our own source; fix requires a major `minimatch` | With the ESLint/Next 16 upgrade |
| Sandbox image — 47 high OS CVEs, no fix available (util-linux mount/nsenter, ncurses, perl, systemd libs) | Container runs `--network none --read-only --cap-drop ALL --security-opt no-new-privileges`, non-root, PID/memory/CPU caps: the affected tools need privileges it does not have | Rebuild the image when Debian publishes fixes (monthly) |
| `bandit` B608 ×41 (SQL built with f-strings) | Every interpolation is a module constant, a placeholder index (`$3`) or an allow-listed ORDER BY; all values are bound parameters. DuckDB identifiers come from `safe_names` (`[a-z0-9_]`) and are quoted — proven by a hostile-header test | — |
| `bandit` B103 (`chmod 0o777` on the sandbox output dir) | Directory lives inside a `mkdtemp` (0700) parent, so other host users cannot reach it; the container's non-root user must write to it through the bind mount | Cloud executor (Lambda) removes the bind mount |
| `bandit` B108 (`/tmp`) | A tmpfs *inside* the container, not a host path | — |
| `gitleaks` aws-access-token in `test_units.py:167` | A made-up AWS-style key used as input to test the output secret filter; allowed by an inline `gitleaks:allow` marker on that one line and by its history fingerprint in `.gitleaksignore`, so any new key is still reported | — |
| Clerk development keys | Local build only | Production Clerk instance before go-live |

## 5. Tests added in this review

| Test | What it proves |
|---|---|
| `apps/api/tests/test_authz_matrix.py` (49) | Generated from the OpenAPI route table: a new route without auth, or an admin route without the admin gate, fails CI |
| `apps/api/tests/test_access_leak_db.py` (2, real Postgres) | Personal documents never reach another user; not-READY documents never retrieved |
| `packages/agents/tests/test_injection.py` (26) | Breakout payloads in a document, CSV cell and DB row stay inside `<tool_data>`/`<context>`; an injected tool request is refused; the offered tool set never changes |
| `packages/datasets/tests/test_datasets.py::test_hostile_headers_cannot_inject_sql` | SQL-shaped CSV headers become safe identifiers; profiling still works |
| `packages/core/tests/test_config.py` | Deployed environments refuse the local storage secret |
| Live spot checks (browser) | Poisoned document and CSV: correct answers, no "PWNED", no prompt or tool disclosure |

## 6. For the pre-go-live penetration test

- Authentication flows on the production Clerk instance (custom sign-in, Google SSO callback,
  session tasks), including account-enumeration behaviour of the sign-in page.
- Admin console: privilege escalation attempts between roles, CSV import with hostile content,
  audit-log integrity.
- Upload pipeline with crafted PDFs/DOCX/XLSX (parser exploits, decompression bombs).
- Data gateway: SQL validator bypass attempts against a real warehouse dialect.
- Rate-limit and stream-cap behaviour behind the production load balancer (real client IPs).
- CSP and headers on the production domain; Clerk bot protection.

## 7. How to re-run

```bash
uv export --frozen --no-hashes --no-emit-project --no-emit-workspace -o /tmp/req.txt
uvx pip-audit -r /tmp/req.txt --no-deps --disable-pip
(cd apps/web && npm audit --omit=dev)
docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:v8.21.2 git /repo --redact \
  --gitleaks-ignore-path /repo/.gitleaksignore
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.57.1 image \
  --severity HIGH,CRITICAL eagleeye-sandbox:1
uvx bandit -r apps packages -x "*/tests/*" -ll
uv run pytest apps/api/tests/test_authz_matrix.py apps/api/tests/test_access_leak_db.py \
  packages/agents/tests/test_injection.py
```
