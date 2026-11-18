# C1 — Frontend

## 1. Stack
Next.js (App Router) + TypeScript (strict), Tailwind + shadcn/ui, TanStack Query (server state), Zustand (UI state), `@clerk/nextjs`, `vega-embed` (charts), `react-markdown` + `remark-gfm` + sanitised HTML, TanStack Table (result tables), `react-pdf` (citation viewer). Hosted as one container on ECS behind CloudFront (static assets cached at edge).

## 2. Layout

```
┌───────────┬──────────────────────────────────────┬───────────────────────┐
│ Left nav  │  Chat                                 │  Right sidebar        │
│ ───────── │  ┌────────────────────────────────┐   │  ┌─ Tabs ───────────┐ │
│ + New chat│  │ message list (virtualised)     │   │  │ Documents │ Data │ │
│ Search    │  │  • user bubble                 │   │  ├──────────────────┤ │
│ Chat list │  │  • assistant: markdown, cites, │   │  │ [Upload  ⬆]      │ │
│  (grouped │  │    table, chart, SQL (collaps.)│   │  │ drag & drop zone │ │
│  by date) │  │  • step tree (collapsible)     │   │  │                  │ │
│           │  └────────────────────────────────┘   │  │ My files         │ │
│ ───────── │  composer: text, attach, send/stop    │  │  ☑ report.pdf  ✓ │ │
│ Profile   │  chips: sources in context            │  │  ☑ sales.csv   ✓ │ │
│ Admin*    │                                       │  │ Enterprise       │ │
└───────────┴──────────────────────────────────────┘  │  ☑ HR policy      │ │
                                                      └──────────────────┘ │
```
- **Right sidebar** (collapsible): *Documents* tab (personal uploads with ingestion status badges UPLOADING→READY, delete, include/exclude toggle for this chat; enterprise docs browse/search, read-only) and *Data* tab (datasets/CSVs with profile preview; permitted DB sources list).
- **Message actions**: copy, regenerate, thumbs up/down, "view steps", "view SQL", download table/chart.
- **Insight panel** (drawer): step tree, per-step tokens/cost/latency, memory/context view (full transparency) — admin/dev toggle in prod.
- Responsive: sidebar becomes a sheet on <1024 px; left nav becomes a drawer.

## 3. Key client modules
| Module | Responsibility |
|--------|---------------|
| `auth/` | Clerk provider, middleware protecting routes, token getter for API client |
| `api/client.ts` | Typed fetch wrapper (OpenAPI-generated types), retry on 5xx/429, injects Bearer token |
| `stream/sseClient.ts` | fetch + ReadableStream SSE parser; verifies gapless `seq`; reconnect with `Last-Event-ID` (backoff 1/2/4 s, max 3) |
| `stream/fold.ts` | Pure reducer: events → message parts (shared fixtures with backend) |
| `chat/*` | Composer, list, message renderers, step tree |
| `upload/*` | SHA-256 in Web Worker → `POST /uploads` → presigned PUT with progress → poll/stream status; chunked for >100 MB (multipart) |
| `charts/VegaChart.tsx` | Renders validated Vega-Lite spec with data from artifact; theme-aware; export PNG/SVG |
| `tables/ResultTable.tsx` | Virtualised, sortable, "download CSV" |
| `citations/*` | Inline `[n]` chips → drawer showing chunk text and PDF page with bbox highlight |

## 4. Streaming UX
- Optimistic user message; assistant placeholder appears on `run.started`.
- Text deltas appended with `requestAnimationFrame` batching; steps update live; progress bar for long analysis (`progress` events).
- **Stop** → `POST /runs/{id}/cancel`; UI shows partial answer marked "stopped".
- Refresh/tab close: on load, `GET /runs/{id}` and re-attach to stream if still running.
- Errors: toast + inline retry; `degraded` flag shows banner ("Answered with limited capability").

## 5. Security (client)
- Markdown rendered with sanitiser (no raw HTML/script, links `rel=noopener noreferrer`, images only from artifact domain).
- CSP: `default-src 'self'; connect-src 'self' api domain clerk domains; img-src 'self' data: artifacts; frame-ancestors 'none'`.
- No secrets in bundle; only Clerk publishable key and API base URL.
- Vega-Lite specs validated with a schema and with expression functions disabled (no arbitrary JS via `expr`).

## 6. Performance & accessibility
Virtualised message list, code-split charts/PDF viewer, skeletons, prefetch chat list. Keyboard shortcuts, ARIA live region for streaming text, focus management, colour-contrast tokens, dark mode.

## 7. Testing
Vitest + Testing Library (reducers, components), MSW for API mocks, Playwright E2E, Storybook for message/step/chart components, visual regression on key states.

## 8. Open UI questions
Branding/theme; whether to show reasoning text to all users; file preview for DOCX/PPTX (convert to PDF server-side?); chat sharing between users (not in v1).
