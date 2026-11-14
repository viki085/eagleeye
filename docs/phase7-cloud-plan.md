# EagleEye — Phase 7: low-cost cloud deployment and scaling proof

> Approved 2026-11-14. Progress and "as built" notes go in `docs/README.md` and the component docs as each part lands.

## Context

Phases 0–6 are done and committed (latest `83b2351`). Everything runs only on your laptop. The roadmap's next milestone is the AWS lift, and the 2,000-user load test was deferred to it.

The original infrastructure design (`docs/components/C10-aws-infra-scaling-cost.md`) targets 10,000 users at roughly $22–30k per month. Your constraints are very different:

- This is a portfolio project. The whole AWS spend must stay within the **$100 free-plan credit**.
- The web app should use the **Vercel free tier**. No paid domain.
- A handful of recruiters should be able to **start the app themselves** and try it.
- Once or twice, a **500–2,000 user load test** is run and recorded on video to show the system scales automatically.
- Database: **Supabase Cloud**. Region: whichever is cheap and available.

So the plan keeps the production architecture (the same containers, the same autoscaling design) but only pays for it while it is in use.

## What I found in the code (drives the plan)

| Finding | Consequence |
|---|---|
| No Dockerfiles for the API, gateway or workers; no CI; no Terraform; **no git remote** | All of this is new. A GitHub repo must be created first (Vercel and CI both need it). |
| `packages/core/eagleeye_core/storage.py` needs static S3 keys and a custom endpoint | Must also accept real S3 with the machine's IAM role (no keys). |
| `AsyncQdrantClient(url=...)` is created in three places with no API key | Qdrant Cloud needs a `QDRANT_API_KEY` setting. |
| The analysis sandbox (`packages/sandbox/eagleeye_sandbox/docker_executor.py`) runs `docker run`, which cannot run on Fargate | The agent only talks to the `AnalysisExecutor` interface (`packages/sandbox/eagleeye_sandbox/types.py`), so a second implementation on AWS Lambda is added. No redesign. |
| Accounts exist only when an admin creates them, and sign-in needs a username or Google (`apps/api/app/auth.py`, the custom sign-in page) | Visitors with only the link cannot get in. A one-click demo sign-in is added. |
| `apps/api/app/auth.py` rate-limits by `request.client.host` | Behind CloudFront or a load balancer every user would share one IP limit. The API must trust the proxy's forwarded address. |
| Clerk development instances are capped at 500 users and production instances need a custom domain | The demo keeps Clerk development keys on the `vercel.app` address. The load test needs its own synthetic sign-in path. |
| Docs already specify the load test as "k6, stubbed LLM (LiteLLM mock mode)" (`docs/02-LLD.md` §load) | Reuse that: no OpenAI cost for the load test. |
| DB pools are fixed per process (API 10, gateway 5, worker `POOL_MAX_SIZE`) | Supabase free allows about 200 pooled connections; pool sizes become settings so many tasks fit. |

## Design: two modes, one set of container images

```
                Vercel (free)  ──  Next.js web app, Clerk dev keys
                      │ HTTPS
                CloudFront (free tier, AWS-provided https address)
                      │
        ┌─────────────┴──────────────┐
   DEMO MODE (default)          SCALE MODE (only during the load test)
   one EC2 machine,             load balancer + ECS Fargate services
   stopped when idle            with autoscaling; created for the test,
   (Docker Compose, same        destroyed straight after
   images)
        └─────────────┬──────────────┘
   Lambda analysis sandbox (both modes, pay per run)
   Supabase Cloud (free) · Qdrant Cloud (free) · S3 · SSM secrets
```

**Demo mode** (what recruiters use)
- One EC2 machine runs the API, data gateway, both workers, Redis and the demo warehouse database with Docker Compose, using the same images as scale mode.
- It is **stopped by default**. A stopped machine costs only its disk (about $1.60 per month).
- When a visitor opens the app while it is asleep, the web app shows "Demo is asleep — Start demo". That calls a small AWS Lambda which starts the machine. It is ready in about 2 minutes.
- The machine **stops itself after 45 minutes with no requests**. A nightly safety rule also stops it if it is still running, and the wake Lambda refuses to start it beyond 6 hours of running time per day.
- All features work, including data-file analysis and charts.

**Analysis sandbox on Lambda** (both cloud modes; Docker stays for the laptop)
- This is the production design already in C10 §2.4. A setting, `SANDBOX_BACKEND=docker|lambda`, picks the implementation.
- The existing `infra/sandbox` image and its `runner.py` are packaged as a Lambda function. A new `LambdaExecutor` implements the same `AnalysisExecutor` interface, so the agent, tools and code checks are unchanged.
- Isolation is at least as strong as today:
  - each run gets its own micro-VM;
  - no network: the function sits in a subnet with no route to the internet;
  - read-only filesystem apart from a small temp folder; non-root; memory and time caps.
- Large data files go through S3 with single-use links that expire. The function's own role has no S3 permissions, and the only S3 location reachable from its subnet is our bucket.
- It runs hundreds of analyses at once with no servers, costs about $0.0002 per 10-second run, and nothing when idle.

**Demo access without an account**
- The sign-in page gets a **"Try the demo" button**. One click signs the visitor in as a shared demo user. No username or password is shown or needed.
- How: a server route on Vercel asks Clerk for a single-use sign-in token for the demo user (valid 60 seconds), and the page signs in with it. The demo account has no password, so there is nothing to leak or change.
- Your own admin sign-in (username or Google) stays as it is.
- The demo user is a normal member: no admin console, no user management, no kill switches, no enterprise document changes.
- Because the account is shared and public:
  - a banner says "Shared public demo — don't upload private files";
  - **every time the machine starts, demo data is wiped and re-seeded** with a sample document, a sample CSV and suggested questions, so each session starts clean;
  - smaller upload limits for the demo user (5 MB per file, 10 files);
  - a **daily model-spend cap for the demo user** (default $2 per day). When it is reached the app says the demo budget for today is used up. This protects your OpenAI bill, which is real money and not AWS credit;
  - the existing limits still apply (20 messages per minute, limited answers at once).
- The button is controlled by a setting and is off by default, so a company deployment never has it.

**Scale mode** (the load test and the video)
- Terraform creates a load balancer and ECS Fargate services for the API, agent worker, ingest worker, data gateway, Redis and demo warehouse.
- Autoscaling: the API scales on CPU and requests per task; the agent worker scales on **queued plus running answers per task** (a custom metric the API publishes), which is the design in C10 §2.4.
- CloudFront is switched to point at the load balancer, so the Vercel web app works against it too (useful for the video).
- It exists for a few hours, then `terraform destroy` removes it. Nothing in it is billed afterwards.
- **All features work, including data-file analysis**, through the Lambda sandbox. This is the same shape a company would run for 10,000 users; only the task counts and the managed Redis differ.

**Services outside AWS (all free plans, no card charge)**
- **Vercel Hobby**: the web app, deployed from GitHub (`apps/web` as the project root).
- **Supabase Cloud free**: two projects, `eagleeye-demo` and `eagleeye-loadtest`, so synthetic load-test users never touch the demo data. Migrations in `supabase/migrations/` apply unchanged with `supabase db push`.
- **Qdrant Cloud free** (1 GB): enterprise document vectors.
- Supabase and Qdrant both suspend free projects after about a week without use. A free weekly GitHub Actions job pings both to keep them awake. If one is ever suspended, reactivating is a button in its console, and `python -m ingest_worker.reindex --all` rebuilds Qdrant.

**Region:** `us-east-1` (N. Virginia). It is generally the cheapest and has every service.

**Deviations from the original design, recorded as ADR-33**
- Web on Vercel instead of ECS.
- No NAT gateway, no ElastiCache, no always-on load balancer, single region, single environment.
- The sandbox follows C10 (Lambda), with Docker kept for local development.
- A public one-click demo sign-in, off by default.
- The full C10 design stays documented as the 10,000-user target; a short "what changes to get there" section is added.

## Cost estimate

Prices are us-east-1 list prices from my knowledge and **must be re-checked in step 7.0** before anything is created. LLM usage (OpenAI) is separate from AWS credit and unchanged from today.

### Standing and demo costs (6 months)

| Item | Basis | Estimate |
|---|---|---|
| EC2 disk while stopped | 20 GB at $0.08 per GB-month | $1.60 / month |
| S3, container registry, logs, Lambda (wake and sandbox), secrets in SSM | small usage | under $1 / month |
| CloudFront | always-free tier | $0 |
| Demo machine while running | about $0.05–0.10 per hour (type chosen in 7.0) | about $6 for 60 hours |
| Fixed address for the machine (only if the free CloudFront private-origin option is unavailable on your account) | $3.65 / month | $0 or $22 |
| **Subtotal** | | **about $22, or $44 with the fixed address** |

### Load test cost by user count

Assumptions: each simulated user sends one message every 2 minutes; answers stream for about 10 seconds from the stubbed model; 5% of messages run a data-file analysis in the Lambda sandbox (under $0.50 for the whole campaign at any size, included below). Prices: Fargate $0.0405 per vCPU-hour and $0.0044 per GB-hour; load balancer about $0.03–0.08 per hour; $0.005 per hour per public address.

| | 500 users | 1,000 users | 2,000 users |
|---|---|---|---|
| Answers in progress at once | about 40 | about 85 | about 170 |
| API tasks (0.5 vCPU) | 2 | 3 | 4 |
| Agent worker tasks (1 vCPU) | 3 | 6 | 11 |
| Other tasks (gateway, Redis, warehouse, k6 load generator) | 4 | 4 | 5 |
| Total vCPU at peak | about 6 | about 10 | about 16 |
| Cost per hour, all-in | about $0.40 | about $0.65 | about $1.05 |
| **Whole test campaign** (about 10 hours: build-up, rehearsals, recorded run) plus logs and data transfer | **about $6** | **about $9** | **about $13** |

**Recommendation:** one recorded run that ramps 500 → 1,000 → 2,000. A ramp is what makes autoscaling visible on video, and the cost difference between sizes is small. The limit is not money but your account's quotas: new AWS accounts often allow only about 6 Fargate vCPUs (which fits 500 users) and about 10 Lambda runs at once. Step 7.0 checks both and requests increases; if the Fargate one is refused, the test runs at 500.

### Total against the $100 credit

| | Estimate |
|---|---|
| Standing and demo costs, 6 months | $22–44 |
| Load test (2,000-user ramp) | $13 |
| Contingency for debugging and mistakes | $15 |
| **Total** | **about $50–72** |

**Guardrails so the credit cannot be overrun**
- The account **stays on the AWS Free plan**. On that plan AWS cannot charge a card: when credits run out the account is closed instead.
- AWS Budgets email alerts at $25, $50 and $75.
- Scale mode has a 4-hour auto-destroy timer, and the demo machine has the idle stop and the nightly stop.
- One thing to confirm in 7.0: AWS's own pages disagree on whether credits expire 6 or 12 months after the account was created. The plan assumes 6.

## Steps

Each part ends with a report and a stop for your approval.

### 7.0 — Preflight (no cost, no code)

Things only you can do (I will give exact click-paths):
1. Confirm the AWS account creation date, the remaining credit and that it is on the Free plan.
2. Create an access profile for Terraform on this machine (`aws configure sso` or an IAM user), so no keys go in the repo.
3. Create free accounts or projects: Vercel, two Supabase projects, one Qdrant Cloud cluster.
4. Decide whether the GitHub repo is private or public.

Things I do:
1. Install the AWS CLI and Terraform locally (neither is installed).
2. Check, read-only, what the Free plan allows: ECS/Fargate, Lambda container images, CloudFront private origins, EC2 instance types, and the Fargate, EC2 and Lambda quotas. Request Fargate and Lambda increases if needed.
3. Re-check every price in the tables above and update the estimate.
4. Create the GitHub repo and push. The playbook PDF at the repo root stays untracked and is never pushed.

**Gate:** if Fargate is not available on the Free plan, scale mode falls back to ECS on small EC2 machines in an auto-scaling group (same task definitions, similar cost). I report before going further.

### 7A — Cloud-ready code, containers and CI (local only, $0)

Tests are written first for each code change.

1. **Containers**
   - `infra/docker/python.Dockerfile`: one multi-stage `uv` image, with a build argument selecting the service (API, gateway, agent worker, ingest worker). Non-root user, health check.
   - `infra/cloud/compose.demo.yml`: the demo-machine stack built from those images plus Redis and the warehouse.
2. **Lambda sandbox**
   - `packages/sandbox/eagleeye_sandbox/lambda_executor.py`: `LambdaExecutor`, same interface and result types as `DockerExecutor`; inputs and outputs through single-use S3 links.
   - `infra/sandbox/lambda_handler.py` and a Lambda variant of the sandbox image, wrapping the existing `runner.py`.
   - `SANDBOX_BACKEND` setting; `apps/agent-worker/agent_worker/runtime.py` and `apps/api/app/services/health_checks.py` pick the implementation from it.
   - The existing sandbox test suite (`packages/sandbox/tests/test_container.py`) is run against both implementations, including the escape attempts (network, file writes, time and memory limits).
3. **Demo access**
   - Migration: `users.is_demo`.
   - Web: "Try the demo" button on the sign-in page and `apps/web/src/app/api/demo-login/route.ts`, which creates the single-use Clerk sign-in token. Shown only when `NEXT_PUBLIC_DEMO_LOGIN` is on. The shared-demo banner.
   - API: demo upload limits and the daily spend cap (`DEMO_DAILY_BUDGET_USD`), checked where the existing usage limit is checked (`apps/api/app/repos/usage.py`, `routers/chats.py`).
   - `scripts/demo_reset.py`: wipes the demo user's chats, documents (with their vectors and stored files) and data files, then re-seeds the samples. Run on every machine start.
   - Tests: the demo user cannot reach admin routes; caps are enforced; the route is absent when the setting is off.
4. **Settings and adapters** (`packages/core/eagleeye_core/config.py` and callers)
   - S3: empty endpoint and keys mean "real S3 with the machine's role"; add `AWS_REGION`. The existing guard against local default keys stays.
   - `QDRANT_API_KEY`, passed in `apps/api/app/main.py`, `apps/agent-worker/agent_worker/runtime.py`, `apps/ingest-worker/ingest_worker/pipeline.py`.
   - Database pool sizes as settings; the Supabase session pooler address is used (works with asyncpg unchanged).
   - Trust the proxy's forwarded client address (uvicorn `--proxy-headers`, limited to the proxy), so per-IP rate limits work.
   - `WEB_ORIGIN` set to the Vercel address (CORS and the Clerk token origin check already read it).
5. **Logs:** JSON log lines with the request ID, for CloudWatch. This closes the item deferred in C9.
6. **Wake and sleep**
   - API: record the time of the last request in Redis.
   - Web: `apps/web/src/app/api/wake/route.ts` (signed-in users only, which includes demo visitors) calls the wake Lambda with a shared secret; an "asleep / starting" screen polls `/v1/health/live`.
7. **Load-test switches** (security-sensitive; reviewed with the security-reviewer agent)
   - A stub model behind the existing LLM gateway port, modelled on `packages/agents/tests/fakes.py::FakeLLM`: canned guard verdicts, optional one search step, text streamed at a realistic speed. Stub embeddings too.
   - A second token verifier for synthetic users, signed with a key generated for the test.
   - Both are accepted **only when `APP_ENV=loadtest`**; startup fails if they are set in any other environment. Tests cover the refusal.
   - `scripts/loadtest_seed.py`: creates the synthetic users and a few enterprise documents in the load-test project.
8. **Queue metric:** the API publishes "queued plus running answers" to CloudWatch every 30 seconds in scale mode (reuses the counts in `scripts/drain_status.py`).
9. **CI** (`.github/workflows/ci.yml`): ruff, Python unit tests, web lint, type check, vitest and production build, gitleaks.
10. **Optional, local, a few cents of LLM cost:** run `evals/sql_eval.py` against the SQL golden set and record the accuracy figure, which closes roadmap milestone 3.

**Verify:** `/verify`; build all images; run the demo stack locally from `compose.demo.yml` against the local Supabase and confirm a document question, a database question and a data-file analysis all work (analysis with the Docker sandbox; the Lambda sandbox is first exercised for real in 7B); the demo button signs in and the reset script leaves a clean seeded account; `APP_ENV=local` refuses the load-test switches. Commit `feat: phase 7a cloud-ready containers and CI`. **Stop.**

### 7B — Demo environment live

1. **Terraform** in `infra/terraform/`
   - `bootstrap/`: the state bucket.
   - `base/` (always present, near-zero cost): network with public subnets only and locked-down security groups; container registry; two S3 buckets; secrets in SSM Parameter Store; least-privilege roles; the demo EC2 machine with a boot script that pulls the current images and starts Compose; CloudFront; the wake Lambda; the sandbox Lambda in its no-internet subnet with the S3-only endpoint; the nightly stop rule; budget alerts; a GitHub sign-in role for CI (no stored AWS keys).
2. **Data:** `supabase db push` to the demo project; create the first admin user and the demo user; run catalog onboarding for the demo warehouse; upload a few sample documents.
3. **Deploy pipeline** (`.github/workflows/deploy.yml`): on `main`, build images, push to the registry tagged by commit, record the tag in SSM; the machine picks it up on next start or by a remote command if it is running.
4. **Vercel:** connect the repo, set the three environment values (API address, Clerk keys), deploy.
5. **Keep-alive job:** weekly ping of Supabase and Qdrant.

**Verify (parity checklist, in a browser against the Vercel address):**
- In a private browser window with no account: "Try the demo" signs in with one click; the asleep screen appears; Start demo brings the app up in about 2 minutes; the machine stops itself 45 minutes after the last request.
- As the demo user: the seeded samples are there; the admin console is refused; the daily cap message appears when the cap is set to a few cents; after a restart, anything the previous visitor uploaded is gone.
- The Lambda sandbox passes the escape tests in the cloud (no network, no credentials of any use, limits enforced).
- As admin: sign in; ask a document question with citations; a database question; upload a CSV and get a chart; open the admin console; kill switches work.
- Streaming works through CloudFront for an answer longer than 60 seconds.
- Security checks: the machine accepts traffic only from CloudFront; buckets are private; no secret is in the repo, the images or the Terraform state output; the wake endpoint refuses unsigned calls.
- Billing console shows the expected daily cost.

Commit `feat: phase 7b demo environment on AWS`. **Stop.**

### 7C — Scale mode, load test, report and video

1. **Terraform `scale/`** (created and destroyed around the test): load balancer, ECS cluster and services, internal service discovery, autoscaling policies, graceful shutdown (120-second stop timeout, Celery warm shutdown), a CloudWatch dashboard (tasks per service, CPU, queue depth, response time, errors), a k6 load-generator task, the 4-hour auto-destroy timer.
2. **k6 script** (`evals/load/chat.js`): each user signs in with a synthetic token, opens a chat, sends a message every 2 minutes and reads the stream to the end. 5% of messages ask for a data-file analysis, which runs real code in the Lambda sandbox. Ramp 500 → 1,000 → 2,000 with holds, then ramp down to show scale-in.
3. **Rehearsal** at 100 users to shake out limits (rate limits, connection pools, Supabase free-plan capacity).
   - If the free Supabase database is the bottleneck at the chosen size, the fallback is a temporary Postgres inside AWS for the test only (about $0.07 per hour).
4. **Recorded run**, then a small **real-model sample** (about 20 real questions on the demo machine) so the report states true answer latency separately from the stubbed scaling numbers.
5. **Failure checks** from C9, kept small: stop an agent worker mid-answer (the answer is retried or resumed); stop Redis (the app recovers).
6. `terraform destroy` for `scale/`; confirm in the billing console that nothing from it is still running.
7. **Report** `docs/load-test-report.md`: setup, what was stubbed and why, results per user level (response times, error rate, tasks over time, cost actually spent), bottlenecks found, and what would change for 10,000 real users.

**Docs:** ADR-33 (lean cloud design), ADR-34 (load-test sign-in and stub model, and their guards); "As built" sections in C10 and C9; README deploy and wake/sleep runbook; a cloud addendum to `docs/security-review-phase6.md`; roadmap status in `docs/README.md`.

Commit `feat: phase 7c autoscaling stack and load test`. **Stop.**

### Not in this phase

- Custom domain, a production Clerk instance and the external penetration test. These need a paid domain and wait for a go-live decision.
- Multi-region, multiple AWS accounts, managed Redis cluster: documented as the 10,000-user target only.
- A read-only view of the admin console for demo visitors. The console is shown in the video instead.

## Decisions for you before approval

1. **Load-test size.** My recommendation: one ramp to 2,000 (about $13), falling back to 500 if the vCPU quota increase is refused.
2. **GitHub repo:** private (default in this plan) or public.
3. **Optional SQL accuracy check** in 7A: include or skip.
4. **Demo daily spend cap:** $2 per day by default. Also set a monthly hard limit in your OpenAI account as a backstop.

## Risks

| Risk | Mitigation |
|---|---|
| The Free plan does not allow a needed service, or quotas are too low | Checked in 7.0 before any build; fallbacks named (ECS on EC2; test at 500) |
| Credits expire 6 months after account creation | Confirmed in 7.0; the load test is scheduled early |
| Free Supabase or Qdrant project suspended or too slow under load | Weekly keep-alive; separate load-test project; temporary Postgres fallback; reindex command |
| Something is left running and drains the credit | Free plan cannot bill a card; budget alerts; idle stop, nightly stop, 4-hour auto-destroy |
| Load-test sign-in or stub model enabled outside a test | Startup refuses them unless `APP_ENV=loadtest`; tests; security review; separate database |
| Anyone with the link can wake the demo and use the model | Running time capped at 6 hours per day and stopped when idle (at most about $0.60 of credit per day); demo model spend capped per day; OpenAI monthly hard limit as a backstop |
| Visitors see each other's chats and uploads in the shared demo account | Banner; data wiped and re-seeded at every start; small upload limits. Separate accounts per visitor were ruled out because Clerk development mode caps users at 500 |
| The demo sign-in is left on in a real deployment | Off by default; a separate setting on web and API; covered by a test and the security review |
| Analysis code escapes or leaks data from the Lambda sandbox | No internet route; function role has no permissions; S3 reachable only for our bucket through expiring single-use links; existing code checks still run first; escape tests run in the cloud |
| CloudFront cuts long answer streams | Read timeout raised; the stream already sends heartbeats and resumes with `Last-Event-ID`; tested in 7B |
| Stubbed results mistaken for real-model performance | The report separates scaling results from the real-model sample |
| Clerk development mode shows a "development" badge and caps users at 500 | Accepted for a demo; removed when a domain is added |

## Sources checked for this plan

- [AWS Free Tier](https://aws.amazon.com/free) and [AWS Free Tier FAQs](https://aws.amazon.com/free/faqs/)
- [AWS Builder Center: the $0 AWS account in 2026](https://builder.aws.com/content/3Kkt4kNiDSUnO3n6db2weSNubzE/the-dollar0-aws-account-in-2026-free-plan-credits-guardrails)
- [CloudFront VPC origins](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.md)
- [Supabase pricing](https://supabase.com/docs/pricing)
- [Qdrant Cloud: create a cluster](https://qdrant.tech/documentation/cloud/create-cluster)
- [Clerk: instances and environments](https://clerk.com/docs/guides/development/managing-environments.md)
