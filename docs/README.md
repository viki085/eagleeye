# EagleEye Documentation

Design, decisions and reports for EagleEye, an enterprise AI assistant that answers from company
documents, databases and data files with verifiable evidence. For an overview, setup and the demo
videos, see the [project README](../README.md).

## Core documents

| # | Document | Contents |
|---|---|---|
| 00 | [Requirements and scope](00-requirements-and-scope.md) | Goals, functional and non-functional requirements, assumptions |
| 01 | [High-level design](01-HLD.md) | Architecture, layers, key flows, technology choices and trade-offs |
| 02 | [Low-level design](02-LLD.md) | Service internals, API contract, sequence flows, state machines, configuration |
| 99 | [Decision log](99-decision-log.md) | Architecture decision records: options, choice, rationale, when to revisit |

## Components

| # | Document | Contents |
|---|---|---|
| 03 | [Data model](components/03-data-model.md) | Postgres schema, object storage layout, Redis keys |
| C1 | [Front end](components/C1-frontend.md) | Chat interface, documents panel, streaming, charts, admin console |
| C2 | [Authentication and access control](components/C2-auth-and-access-control.md) | Clerk, roles, document access, data-source permissions |
| C3 | [Agent orchestration](components/C3-agent-orchestration.md) | Guard, router, supervisor, tools, budgets |
| C4 | [Retrieval-augmented generation](components/C4-rag.md) | Ingestion, hybrid retrieval, enterprise and personal scope |
| C5 | [Text-to-SQL and data gateway](components/C5-text-to-sql-data-gateway.md) | Natural language to validated, read-only SQL |
| C6 | [Analysis, notebooks and charts](components/C6-eda-analysis-charts.md) | Data-file profiling, cross-source analysis, sandbox, chart specifications |
| C7 | [Memory and context](components/C7-memory-and-context.md) | Conversation context, summaries, token budgets |
| C8 | [Guardrails and security](components/C8-guardrails-security.md) | Defence in depth and threat model |
| C9 | [Observability and evaluation](components/C9-observability-evaluation.md) | Logging, metrics, evaluation harnesses |
| C10 | [Infrastructure, scaling and cost](components/C10-aws-infra-scaling-cost.md) | Local stack, AWS deployment, capacity and cost model |

## Reports

| Document | Contents |
|---|---|
| [Load test report](load-test-report.md) | 2,000 concurrent users on ECS Fargate: method, results, findings |
| [Security review](security-review-phase6.md) | Threat review, controls and scan results |

## Plans

Working plans kept as a record of how each stage was delivered.

| Document | Contents |
|---|---|
| [Cloud deployment](phase7-cloud-plan.md) | Demo mode on AWS and Vercel, scale mode on ECS Fargate |
| [Enterprise demo data](phase7-enterprise-data-plan.md) | The Grand Line Shipping Company warehouse, documents and data files |
| [Notebook analysis](notebook-eda-plan.md) | Step-by-step exploratory notebooks |
| [Product video](video-production-plan.md) | Production plan for the product demo video |
| [Architecture and load-test video](architecture-loadtest-video-plan.md) | Production plan for the architecture and scaling video |

## Key decisions

Full rationale for each is in the [decision log](99-decision-log.md).

| Area | Decision |
|---|---|
| Scale | Designed for 10,000 registered users; 1,000 concurrent chats at peak, 2,000 in bursts (verified by the [load test](load-test-report.md)) |
| Models | OpenAI models through LiteLLM, with fast and capable tiers and automatic fallbacks; provider set by configuration |
| Agent framework | LangGraph behind thin internal interfaces |
| Vector storage | Qdrant for enterprise documents, pgvector for personal documents |
| Enterprise data | SQL databases through a read-only data gateway with a semantic catalog |
| Document sources | Administrator uploads and object-storage sync |
| Tenancy | Single enterprise tenant; schema ready for multiple organisations |
| Web search | Not offered: answers come from enterprise data only |
| Write actions | None: the platform is read-only, so no human approval step is needed |
| Backend | Python 3.12 and FastAPI |
| Infrastructure | Docker Compose locally; Terraform, AWS and GitHub Actions in the cloud |

## Delivery status

| Milestone | Scope | Status |
|---|---|---|
| 1 | Authentication, chat, streaming, chat history | Complete |
| 2 | Document retrieval with citations | Complete: recall@5 of 0.87 on 150 questions |
| 3 | Text-to-SQL through the data gateway | Complete: 96% execution accuracy on a 52-question golden set |
| 4 | Data files, cross-source analysis, notebooks and charts | Complete |
| 5 | Guardrails, rate limits, admin console, security review | Complete |
| 6 | AWS deployment: demo mode, scale mode, load test to 2,000 users | Complete: 15,417 answers, 99.99% success |
