# EagleEye — Phase 7 addendum: realistic enterprise data (logistics)

> Status: **approved 2026-11-14.** Part of Phase 7 (`docs/phase7-cloud-plan.md`); runs as step **7A-D**, before the demo goes live in 7B.

## Context

The demo data today is a toy: an "Acme" retail warehouse with rows such as "Customer 1" and "Electronics item 3", plus 10 short fixture documents. It does not look like an enterprise system to a recruiter.

Decisions:
- **Domain:** global container shipping and freight logistics.
- **Source:** hybrid. The company's own data is generated so the database, documents and data files agree with each other. Real public documents and datasets sit alongside it as reference material.
- **The company is fictional:** **Grand Line Shipping Company** (short form GLSC). It has the shape and scale of a large carrier but no real company's name, logo or branding.
- **Grand Line becomes the only data the application uses**, locally and in the cloud, and the basis of the evals. The Acme toy data is decoupled from the application (section 6) and deleted in a later cleanup.

## The company: Grand Line Shipping Company

- Container shipping line plus inland trucking and warehousing; headquarters in Rotterdam; regional offices in Singapore, Dubai, New York, Santos and Shanghai.
- 120 vessels on 38 services across 6 trade lanes, calling at about 220 real ports.
- About 8,000 shipper customers (fictional names); about 6,000 employees.
- The story runs **January 2024 to October 2026**, with real-world-style events built into the numbers: a Red Sea diversion period that lengthens Asia–Europe transit times, a peak season each autumn, a port strike, a cyber incident and a reefer (refrigerated cargo) failure claim. These give questions like "why did Asia–Europe on-time performance drop in Q1 2024?" real answers that the documents explain and the database confirms.

## What gets built

### 1. Operations warehouse (Postgres, data-gateway source `grandline_ops`)

Replaces the Acme warehouse in `infra/docker-compose.yml` (same `warehouse` service, same `WAREHOUSE_DSN` setting, new database `grandline`). The gateway and catalog code are unchanged.

| Schema | Tables (approximate rows) |
|---|---|
| `network` | ports (220, real UN/LOCODEs and coordinates), terminals (300), services (38), service rotations (400), vessels (120), voyages (7,000), port calls (75,000) |
| `commercial` | customers (8,000), contracts (12,000), rate cards (150,000), bookings (1.1 M), booking containers (1.7 M) |
| `equipment` | containers (180,000), tracking events (2.2 M) |
| `finance` | invoices (1.1 M), invoice lines (2.4 M), bunker fuel purchases (40,000), claims (14,000) |
| `operations` | delay incidents (25,000), emissions per voyage (7,000), trucking jobs (300,000), warehouse inventory snapshots (200,000) |
| `hr` | employees (6,000, with PII marked: name, email, salary) |

- **About 9.5 million rows, 1.5–2 GB on disk.** Large enough that the existing "query too expensive" guard has something to protect against, small enough for the demo machine's disk and a quick load in scale mode.
- Realistic distributions: seasonality, lane-specific transit times, a long tail of small customers and a few giant ones, price movements following the real oil price, outliers and a little dirty data (late invoices, missing seal numbers).
- Generated with a fixed random seed by `infra/warehouse/generate.py` (numpy, Faker), loaded with Postgres `COPY`. Same data on every machine.
- The cloud gets a compressed dump (about 300 MB) in S3; the demo machine and the scale-mode warehouse restore from it.
- A curated catalog file `packages/catalog/eagleeye_catalog/seeds/grandline_ops.yaml` with plain-English table and column descriptions, PII flags, role grants (members can't see `hr` salaries or customer contact details; data admins can) and about 40 verified example questions.

### 2. Enterprise documents (about 500 files, about 20,000 chunks)

Written for Grand Line, and **grounded in the warehouse**: every figure, booking number, vessel and incident a document mentions is read from the generated database first, so the documents and the data agree.

| Type | Count | Format |
|---|---|---|
| Policies and SOPs: dangerous goods, reefer monitoring, customs clearance, demurrage and detention, claims handling, cybersecurity, procurement, HSE, code of conduct, travel and expenses | 70 | PDF, DOCX |
| Customer service agreements (rates match the rate cards in the database) | 80 | PDF |
| Carrier, terminal and trucking subcontractor agreements | 30 | PDF |
| Delay and incident investigation reports (one per major incident in the database) | 120 | DOCX, PDF |
| Monthly and quarterly operations reports (figures computed from the database) | 46 | PDF |
| Board and strategy decks | 12 | slide-style PDF |
| Port and terminal profiles | 40 | Markdown |
| Training material, meeting minutes, IT runbooks | 60 | DOCX, Markdown, text |
| Real public reference documents (see section 4) | about 40 | PDF |

- Generated by `data/grandline/make_docs.py` with the existing fast model (gpt-6-luna); real PDF and DOCX files built with the same libraries as the current fixtures.
- Some documents are marked internal and some restricted (for example HR investigations), so access control can be shown.

### 3. Data files for analysis (10 files, 5–25 MB each)

For the data-file analysis feature and the demo's suggested questions:
- container fleet utilisation by week (CSV, 200k rows)
- customer satisfaction survey 2026 (CSV, 50k rows, free-text comments)
- demand forecast by trade lane (XLSX, several sheets)
- port congestion by week (CSV)
- fuel cost and consumption by vessel (CSV)
- carrier scorecards (XLSX)
- real public datasets (see section 4): daily Brent crude price and US port container volumes.

### 4. Real public material (the "hybrid" part)

Only sources whose licence clearly allows reuse; an attribution file `data/grandline/SOURCES.md` lists each one with its link and licence.

| Material | Source | Licence |
|---|---|---|
| Customs compliance guides | US Customs and Border Protection "Informed Compliance" publications | US government work, public domain |
| Hazardous materials transport guidance | US DOT PHMSA | public domain |
| Demurrage and detention rules | US Federal Maritime Commission (46 CFR 545.5) | public domain |
| Port and freight statistics | US Bureau of Transportation Statistics | public domain |
| Daily Brent crude price (drives Grand Line's simulated fuel costs) | US Energy Information Administration | public domain |
| Port locations and codes | UN/LOCODE | free to use |
| EU maritime and emissions rules (ETS for shipping, FuelEU Maritime) | EUR-Lex | reuse allowed with attribution (Commission Decision 2011/833) |

IMO conventions, Incoterms and commercial freight indices are **not** included: they are copyrighted or paid. The documents may mention them by name.

### 5. Demo seeding and evaluation

- The cloud demo, your local app and the demo account's suggested questions all use Grand Line, with about 15 starter questions that show each capability, for example:
  - "Which trade lane had the worst on-time performance in Q1 2024, and what caused it?" (database plus incident reports)
  - "Chart monthly bunker cost per TEU against the Brent price" (database plus a public data file)
  - "What does our reefer SOP require when a temperature alarm goes off, and how many reefer claims did we pay in 2025?" (documents plus database)
- New evaluation sets replace the Acme ones: about 60 SQL questions with checked answers, about 100 retrieval questions and the analysis set rebuilt on the Grand Line data files. The existing eval scripts are pointed at them.
- `scripts/start --onboard` loads Grand Line on your PC (one time).

### 6. Decoupling the Acme toy data

Moved, not deleted, so nothing in the application, the start script, the evals or the tests depends on it. A later cleanup deletes the folder.

- **Moved to `legacy/acme/`:**
  - the warehouse SQL (`infra/warehouse/01_schema.sql`, `02_seed.sql`, `03_roles.sql`)
  - the catalog seed `acme_warehouse.yaml`
  - the eval sets `sql_golden.jsonl`, `analysis_golden.jsonl`, `retrieval_golden.jsonl`
  - the fixture generators and files in `evals/fixtures/` (the 10 documents, CSVs and workbook)
- **Repointed to Grand Line:** `infra/docker-compose.yml`, `scripts/eagleeye.py` (onboarding), `README.md`, the catalog CLI help text, the eval scripts, and the one catalog test that loads the Acme seed file.
- **Unit tests** that only use "acme" as a made-up label inside fakes (for example `packages/agents/tests/sql_fakes.py`) don't depend on the toy data. They are relabelled to Grand Line so nothing mentions Acme.
- **Your local data:**
  - the Acme source is removed from the local catalog;
  - the 10 fixture documents are deleted from the local document library;
  - the old warehouse Docker volume is kept until the cleanup, so you can roll back.

## Budget check

| Limit | Use | Headroom |
|---|---|---|
| Qdrant free, 1 GB | 20,000 vectors at 1,536 dimensions, about 180 MB including index | large |
| Supabase free, 500 MB database | chunk text and full-text index for 20,000 chunks, about 130 MB, plus app data | about 300 MB left |
| Demo machine disk (20 GB) | warehouse 2 GB, images about 3 GB | fine |
| S3 | dump 300 MB, documents about 1.5 GB, at $0.023 per GB-month | about $0.05 per month |
| One-off OpenAI cost (not AWS credit) | writing documents with gpt-6-luna about $2–5; embeddings about $0.30; eval runs about $1 | **about $5 in total** |

The AWS estimate in the Phase 7 plan rises by under $1.

## Steps

1. Decouple Acme (section 6); the test suite must still pass.
2. Generate the warehouse; check row counts, distributions and the built-in events; write the catalog and onboard it locally.
3. Generate the documents and data files from the warehouse; collect the public material and its attribution.
4. Ingest everything locally through the real pipeline; build the evaluation sets and run them.
5. Spot-check in the browser: the 15 starter questions, the restricted-document and PII checks.
6. Commit generators, catalog, evaluation sets and attribution. Generated output larger than a few MB is **not** committed; it is rebuilt with one command (or uploaded to S3 for the cloud).

**Verify:** full test suite passes with no reference to Acme outside `legacy/`; the new evals are reported (SQL execution accuracy, retrieval budget recall, analysis pass rate); `scripts/start` works locally.

## Risks

| Risk | Mitigation |
|---|---|
| Generated documents read as generic or contradict the data | Every document is written from facts pulled from the warehouse; a checker re-reads each one for figures and IDs and compares them with the database |
| Larger tables slow the warehouse | Indexes for common questions; the existing row-estimate guard; tested at load-test scale in 7C |
| Synthetic names resemble real companies or people | Faker names, and a block-list of real carrier and port-operator names checked before writing |
| Supabase free database fills up | Chunk count capped at about 20,000; sizes checked after ingest |
| Eval scores change because the data is harder | Reported as a new baseline, not compared with the Acme numbers |
