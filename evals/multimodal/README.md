# Multimodal PDF eval (Phase 0 of the multimodal RAG plan)

Test set and scorer for PDFs with tables, images, watermarks and scanned pages. Built 2026-11-17
(the test set in a side session, the scorer in the main one).

## What is here

| File | What it does |
| --- | --- |
| `build_corpus.py` | Downloads 10 public-domain US government PDFs into `pdfs/` and writes `corpus/`: 11 test documents, 96 pages, plus `corpus/manifest.json`. Kinds: `text`, `scanned` (no text layer, skewed), `mixed` (first 3 pages scanned), `watermark` (diagonal CONFIDENTIAL + DRAFT footer), `deck` (chart pages as images, title only). |
| `build_golden.py` | Writes `golden.jsonl`: 150 questions, each with a short answer span checked verbatim against the ORIGINAL page text, plus doc, page and tag (`text` 105, `table` 11, `image` 20, `scanned` 14). Run with the main `.venv` (uses the app's LLM gateway, about $0.05). |
| `build_table_golden.py` | Adds table questions (`t001`...): each test PDF is parsed, and for up to 4 tables per document the fast model writes questions answered by one cell. An answer is kept only if it is in the ORIGINAL page text, has a digit or two or more words, and is not repeated on that page. 32 questions (24 `table`, 8 `scanned` from the scanned copper report), about $0.03. Re-running replaces them. |
| `run_docling.py` | Standalone Docling run (default settings, RapidOCR, picture classification) into `out/docling/`, with `summary.json`. Not the shipped parser. |
| `.venv/` | Own Python 3.12 env (docling 2.150.1, CPU torch, docling-parse, rapidocr, reportlab, pypdf). Git-ignored, as are `pdfs/`, `corpus/*.pdf` and `out/`. |

Run order: `evals/multimodal/.venv/Scripts/python.exe evals/multimodal/build_corpus.py`, then
`.venv/Scripts/python.exe evals/multimodal/build_golden.py`.

Gotcha: never name a script here `docling_parse.py`; it hides the `docling_parse` package and
Docling then reports "docling-parse package is required".

## Results so far

Old pypdf parser (`ingest_worker.parsing.pdf.PdfParser`): 3 of 11 FAIL (deck, both scanned
files: "No extractable text"); both watermark files carry CONFIDENTIAL and DRAFT on all 12
pages; the mixed file is READY but its 3 scanned pages are silently empty.

Standalone Docling (no clean step): 11 of 11 succeed; 0.7 to 2.0 s/page on text, 4.4 to 5.6 s/page
on scanned (laptop CPU); tables found; pictures classified (line/bar/pie charts, logos, maps,
photos). DRAFT footer dropped as page furniture, but the diagonal CONFIDENTIAL leaks on 10 and 12
pages of the two watermark files.

## Scorer (`score.py`)

`uv run --package eagleeye-ingest-worker python evals/multimodal/score.py` (local Supabase up,
corpus built). Runs each parser through the real pipeline (shipped chunker, embedding text,
pgvector + full text for a temporary eval user, the real Retriever, rewriting off) and reports
READY documents, pages with text, table chunks, chunks holding a manifest watermark string (text
or heading path), seconds per page, and budget_recall / recall@5 / MRR overall, per tag and per
document kind. Spans match as whole words of letters and digits. Writes `out/scores.json`.

## Scores (2026-11-17, 150 questions)

| Parser | READY | Pages with text | Watermark chunks | budget_recall | without the date cluster |
| --- | --- | --- | --- | --- | --- |
| pypdf (before Phase 1) | 8/11 | 76/96 | 35 | 0.79 | 0.77 |
| Docling as first shipped (a08e6bb) | 11/11 | 89/96 | 0 | 0.89 | 0.88 |
| Docling with the eval fixes | 11/11 | 93/96 | 0 | 0.89 to 0.92 | 0.95 |
| + compact tables (Phase 2) | 11/11 | 93/96 | 0 | 0.92 | **0.99** |
| + figures saved and described (Phase 3) | 11/11 | 93/96 | 0 | 0.89 to 0.94 | 0.95 to 0.97 |
| + reranker (Phase 4, `--rerank`) | 11/11 | 93/96 | 0 | **0.98** | **0.98** |

Per tag, Docling with compact tables vs pypdf: image 1.00 vs 0.25, scanned 0.93 vs 0.29, table
1.00 vs 0.91 (11 vs 10 of 11), text 0.90 vs 0.94 (the date cluster is all text questions).
Compact tables: Docling pads every cell to its column width, so wide tables were mostly spaces;
stored and embedded without the padding they fit whole (table chunks 47 -> 19) and rank higher.

What the scorer found and fixed in the parser:
- a text block printed over a watermark was taken for a picture, and the picture's 40 lines were
  skipped: a whole page lost. Text inside pictures is now kept (`traverse_pictures`), which also
  lifts the chart questions from 0.65 to 1.00;
- diagram labels inside pictures ("GOVERN", "RECOVER") became headings and filed the cover page
  under them: text inside a picture is never a heading;
- tables of contents and indexes (`document_index`) and checklist lines (`checkbox_*`) were
  skipped; they are kept as plain lines with dot leaders removed (as Markdown tables they were
  mostly dots and crowded out real answers);
- pypdf reads an ALL CAPS watermark as a heading, so it leaks through chunk breadcrumbs: the
  watermark check covers heading paths.

Caveats:
- The date cluster: 10 of NIST's 18 questions share one answer ("February 26, 2024"). pypdf
  always finds it because the date is in every page's running header; Docling drops running
  headers, leaving the date in one short cover chunk, so those 10 swing between 0 and 5 from run
  to run. Read the "without the date cluster" column; a fix to consider is keeping page 1's
  header and footer text, which often carries the date and document number.
- Remaining misses are mostly ranking, not parsing (the span is in a chunk that does not reach
  the top results): wide tables embed poorly (Phase 2: embed caption, header and a preview) and
  a reranker is Phase 4.
- Runs vary by one or two questions outside the date cluster.

Phase 3 (`--describe` runs real figure descriptions, about $0.01): every chart or picture of at
least 1 inch becomes its own chunk (caption, the vision model's description, the words printed in
it) with the stored PNG. Retrieval stays within noise of Phase 2 (one to three questions lower:
about 35 figure chunks now compete for the top results; the answers are still in the chunks, so
the Phase 4 reranker is the fix). The vision model can name a watermark it sees; the stamps the
clean step removed are stripped from descriptions too (watermark chunks back to 0).

Phase 4: the fast model reorders the fused candidates (25 previews of 600 characters; the scorer
keeps 20, production 5 of 20). recall@5 0.89 -> 0.98, MRR 0.78 -> 0.95, and the date cluster
10/10: the answers were already retrieved, only ranked too low. Costs one fast call per question.

## 182 questions (2026-11-17, table questions added)

`build_table_golden.py` added 32 table questions (table-tagged answers 11 -> 35). Docling with
the continued-table fix, `--describe --rerank`: budget_recall 0.978, recall@5 0.978, MRR 0.939;
by tag image 0.95, scanned 0.955, table 0.971, text 0.990. Misses: m035, m088, m142, t015 (a
"3-month average" cell in the BLS industry table).

Continued tables: a table that runs onto the next page comes out of Docling as two tables, and the
second takes its first data row for a header. The second part now gets the first part's header
row (it stays its own chunk with its own page). Found in the live library: all 80 service
agreements have a rate table that breaks across pages 1 and 2, and the page-2 rows could not be
found.

## Not done

- Fewer questions sharing one answer (the NIST date cluster).
