# C4 — RAG (Enterprise + Personal Documents)

## 1. Why RAG (not fine-tuning / long-context)
Enterprise documents change often; RAG updates instantly, supports per-document ACLs and citations. Long context cannot hold 5M chunks, and cannot enforce per-user access. Fine-tuning leaks access boundaries and needs retraining.

## 2. Two scopes, two stores (ADR-04)
| Scope | Who uploads | Who can retrieve | Metadata (Supabase PG) | Vector store |
|-------|-------------|------------------|------------------------|--------------|
| `enterprise` | Knowledge admins (UI or object-store sync) | Users in `document_acl` groups (empty = all) | `documents.scope='enterprise'` | **Qdrant** (`enterprise_chunks` collection, filtered-ANN on ACL payload) |
| `personal` | Any user | Owner only | `documents.scope='personal', owner_id=user` | **Supabase pgvector** (RLS-backed) |

`document_chunks` in Supabase PG is the system of record for chunk text/metadata in both scopes; scope/owner/ACL attributes ride on **each chunk** (Qdrant payload or PG columns) so filters are applied inside the vector query. Query-time default: search **both** scopes (fan out to both stores, merge via RRF), results labelled by origin; user can narrow in the sidebar (selected docs → `doc_ids` filter).

## 3. Ingestion pipeline

```mermaid
flowchart LR
  A[Browser: SHA-256] --> B[POST /uploads → presigned PUT]
  B --> C[(SeaweedFS/S3 original)]
  C -->|upload-complete signal| Q[(Redis: ingest Celery queue)]
  Q --> W[Ingest worker]
  W --> S1[1 Scan: type/size check + Phase 2 GuardDuty]
  S1 --> S2[2 Parse]
  S2 --> S3[3 Chunk]
  S3 --> S4[4 Enrich tables/images]
  S4 --> S5[5 Embed]
  S5 --> S6[6 Upsert — dual-store routing + READY]
```
1. **Scan**: allow-list MIME (pdf, docx, pptx, txt, md, html, xlsx, csv); size limits; basic MIME + magic-byte check (Phase 1). Phase 2 adds GuardDuty Malware Protection for S3 and Macie/Comprehend PII tagging for enterprise docs.
2. **Parse**: `unstructured` (hi-res for PDF) or `docling`; `unstructured` OCR mode for scanned pages/forms (text density check). Phase 2 can swap to Amazon Textract for higher accuracy on complex forms. Output elements: title, narrative, list, table (as HTML), image (saved to SeaweedFS/S3), with page and bounding boxes.
3. **Chunk**: structure-aware `chunk_by_title`: max ~800 tokens (≈3,000 chars), soft limit 600 tokens, merge tiny sections (<150 tokens), 10–15% overlap only inside long sections; every chunk carries `heading_path` ("Policy › Returns › Electronics") — fixes the playbook's failure case of return and shipping policy sharing a chunk. Tables and images are standalone chunks.
4. **Enrich**: tables and images summarised by a vision-capable capable-class/fast-class LLM call into `content_processed` (searchable text) while `content_original` (HTML/image ref) is kept immutable for faithful answering. Batch and cache by content hash.
5. **Embed**: provider embedding model (`EMBED_MODEL` env var — e.g. `text-embedding-3-small` via OpenAI/LiteLLM or `nomic-embed-text` via Ollama; batched, normalised); content prefixed with title + heading_path for context ("contextual chunk headers").
6. **Upsert**: idempotent by `chunk_hash`; set `acl_group_ids`; **dual-store routing**: scope=`enterprise` → Qdrant collection; scope=`personal` → Supabase pgvector. Mark `READY`. Stage progress to `documents.stage_detail` and Redis → UI progress.

CSV/XLSX are **not chunked for RAG** by default; they go to the dataset pipeline (C6). A short schema+profile summary chunk is indexed so questions like "which file has customer churn?" can find them.

Failure handling: each stage retried 3× with backoff; poison messages → DLQ + `documents.status=FAILED` with reason visible to the user; reprocess endpoint for admins. Deleting a document removes chunks (cascade) and queues S3 cleanup. Re-upload of changed enterprise file creates a new version; old chunks deleted after the new version is READY (no gap).

## 4. Retrieval pipeline (deterministic; one LLM call)

```
question + chat context
  → [fast-class LLM] query rewrite: standalone question + 3–5 variants (keywords, synonyms, sub-questions)
  → for each variant, in parallel:
        vector search (HNSW, top 20) ∩ ACL/scope/doc filters
        keyword search (tsvector/BM25, top 20) ∩ same filters
  → Reciprocal Rank Fusion per query (weights 0.7 vector / 0.3 keyword; k=60)
  → RRF across variants (equal weights) → top 12
  → optional rerank (Cohere Rerank API or local cross-encoder) → top 4–6   [flag, off by default]
  → relevance threshold check (calibrated; default floor via eval)
  → expand: neighbouring chunk(s) for same heading when chunk is a continuation
  → return chunks + citation metadata
```
- **Hybrid** because users mix semantic questions with exact terms (policy IDs, product names, error codes).
- **Rerank** is optional: adds ~150–300 ms; enable if eval shows recall@5 gain justifies it (playbook trade-off).
- **Threshold**: if best score below floor → return `low_relevance=true`; agent must say so rather than answer from priors.
- **Dual-store retrieval**: enterprise scope → Qdrant (filtered-ANN, unlimited scale); personal scope → Supabase pgvector (HNSW with iterative scan for selective filters; exact scan via partial index on `(owner_id)` for small personal sets). Mixed queries fan out to both and merge via RRF before rerank.
- Token budget: ≤ 1,500–2,500 tokens of context injected; chunks truncated with markers.

## 5. Answering & citations
Prompt: answer **only** from `<context>` chunks; cite `[n]`; if insufficient say so; quote tables from `content_original`. Server maps `[n]` → `{document_id, chunk_id, page, bbox}` and emits `citation` events; UI opens the chunk/page. Enterprise citations the user cannot access are impossible (retrieval already filtered); an output assertion re-checks.

## 6. Semantic cache (enterprise-only answers)
Cache key = normalised-question embedding bucket + **scope hash** (set of ACL groups + selected sources + corpus version). Only used when the answer was built **solely from enterprise docs** and contained no personal/SQL data. Corpus version bump (any enterprise doc change) invalidates. Expected 20–30% hit rate on FAQ-style traffic; mitigates cost and latency.

## 7. Capacity (v1)
Enterprise (Qdrant): 5M chunks × ~1.5 KB (1024-d float32 + payload) ≈ ~8 GB — comfortably in Docker (Phase 1) or Qdrant ECS (Phase 2); unlimited scale via collection sharding. Personal (Supabase pgvector): small per-user sets, HNSW index per partial-index strategy; trivial sizing for v1. Ingestion throughput: ~10–20 docs/min per Celery worker; scale worker concurrency on Redis queue depth (target backlog drains < 10 min).

## 8. Quality evaluation
Golden set (≥ 150 Q/A with source chunks across enterprise + personal): recall@k, MRR, answer faithfulness (LLM-judge + human spot checks), citation precision. Run on every change to chunking/embedding/prompt; nightly on prod-like index. Embedding model change = full re-index in shadow column, compare, swap.

## 9. Open questions
- Languages besides English? (affects embedding model/tokenizer choice).
- Do enterprise docs have existing labels/classification we should import as ACLs?
- Connectors (SharePoint, Confluence, S3 sync) priority for v1 vs v2 (D4).
