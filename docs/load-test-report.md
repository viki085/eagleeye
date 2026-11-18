# Load Test Report: 2,000 Concurrent Users

**Date:** 18 November 2026 · **Environment:** dedicated scale stack on AWS (ECS Fargate, us-east-1),
destroyed after the test · **Tooling:** k6 on Fargate, CloudWatch, the EagleEye admin console

## Summary

EagleEye was driven from 1 to 2,000 concurrent users in steps, with autoscaling enabled and every
service starting from a single task.

| Metric | Result |
|---|---|
| Peak concurrent users | **2,000** |
| Answers served | **15,417** in 23 minutes |
| Failed answers | **2 (0.013%)** |
| Response time, whole run | average **12.6 s**, p95 **29.9 s** |
| Peak capacity | 11 agent workers, 4 API tasks |
| Estimated model cost at production rates | **$6.41** (≈ $0.0004 per answer) |

Each step in load produced a short rise in response time while new workers started, after which
response times returned to their baseline:

| Step | Before scaling (avg / p95) | After scaling (avg / p95) | Agent workers |
|---|---|---|---|
| 50 → 500 users | 27.0 s / 39.2 s | 7.7 s / 12.2 s | 1 → 5 |
| 500 → 1,000 users | 12.2 s / 13.0 s | 6.1 s / 12.2 s | 5 → 7 |
| 1,000 → 2,000 users | 25.9 s / 42.0 s | 11.9 s / 13.6 s | 7 → 9 (11 at peak) |

## Method

### What was real, and what was simulated

Everything except the language model ran exactly as in production: sign-in tokens, the API, the
queue, agent workers, the ingest pipeline, Postgres, Qdrant, the read-only data gateway with SQL on
the operations warehouse, the Lambda analysis sandbox, guardrails, the security-event log and the
admin console.

The language model and embeddings were replaced by a built-in stand-in (`LLM_PROVIDER=stub`,
allowed only with `APP_ENV=loadtest`, ADR-34). It answers with realistic timing and token volumes,
returns vetted SQL for database questions, a valid notebook for analysis requests and scripted
guard verdicts for attacks. Simulating the model kept the test's model cost at zero and made
results repeatable; the cost above prices the recorded token counts at the production model's
rates.

### Load profile

Synthetic users signed in with load-test tokens, opened a chat and asked a question every 60–90
seconds, reading each answer's event stream to the end. Each chat held five questions.

| Stage | Users | Duration |
|---|---|---|
| Smoke | 1 | 2 min |
| Hold | 50 | 3 min |
| Step and hold | 500 | 4 min |
| Step and hold | 1,000 | 4 min |
| Ramp and hold | 2,000 | 7 min |
| Ramp down | 2,000 → 0 | 3 min |

### Question mix

| Type | Share (planned) | Share (observed) | Path exercised |
|---|---|---|---|
| Document questions | 90% | 89.0% | hybrid retrieval, citations |
| Database questions | 3% | 3.7% | SQL writer, validator, data gateway |
| Chart questions | 3% | 2.8% | SQL, then chart specification |
| Attacks | 3% | 3.3% | guard, SQL validator, security events |
| Notebook analyses | 1% | 1.2% | Lambda sandbox (Python) |

Attacks covered prompt injection, system-prompt extraction, role-play jailbreaks, personal-data
exfiltration, credential fishing, harmful requests, requests for role-restricted HR data and SQL
injection inside a question. All were blocked: by the guard, or by the worker's SQL validator
before any query reached the database.

### Infrastructure under test

| Service | Size per task | Scaling |
|---|---|---|
| API | 0.5 vCPU, 1 GB | 1–6 tasks, CPU target 50% |
| Agent worker (40 concurrent answers) | 1 vCPU, 2 GB | 1–12 tasks, step scaling on answers in progress per worker (1-minute alarm) |
| Data gateway, ingest worker | 0.5–2 vCPU | CPU target |
| Postgres (app database), Qdrant, Redis, operations warehouse | 1–2 vCPU | fixed, one task each |

A one-time schedule scaled every service to zero four hours after creation as a safeguard; the
stack was removed with `terraform destroy` immediately after the test.

## Findings and changes made

The 100-user rehearsal before the recorded run surfaced four issues, all fixed before the run:

1. **Scaling reacted too slowly.** Target tracking waited three minutes over target before adding
   workers. Agent workers now step-scale on a one-minute alarm, adding two to six tasks depending on
   how far the load is above target.
2. **Workers were limited by slots, not compute.** At eight answers per worker, CPU stayed below
   15%. Each worker now runs 40 answers concurrently, with a larger database pool.
3. **The app database allowed 100 connections**, fewer than the peak demand of roughly 400. The
   limit was raised to 500.
4. **Refused SQL was invisible to administrators.** Queries rejected by the worker's validator never
   reached the gateway's audit log. They are now recorded in the SQL log, and attempts on
   restricted data or unsafe SQL also appear as security events.

Two observations remain for future tuning:

- At 2,000 users the agent workers took about three minutes to catch up; a higher starting count or
  predictive scaling would shorten the peak.
- The API scaled late (CPU-based); scaling it on request rate or open streams would track load more
  closely.

## Reproducing the test

The stack, scripts and recorder are in the repository:

| Part | Location |
|---|---|
| Scale stack (Terraform) | `infra/terraform/scale/` |
| Database and k6 images | `infra/loadtest/build-images.sh`, `infra/loadtest/build-k6.sh` |
| Load script and question pool | `evals/load/chat.js`, `evals/load/build_pool.py` |
| Synthetic users and seeding | `scripts/loadtest_seed.py` |
| Per-minute export | `media/arch-load/export.py` |

The test cost a few dollars of AWS usage and no model fees.
