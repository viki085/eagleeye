# Multimodal PDF eval (Phase 0 of the multimodal RAG plan)

Test set for PDFs with tables, images, watermarks and scanned pages. Built 2026-11-17 in a side
session and handed over to the main session; not yet committed.

## What is here

| File | What it does |
| --- | --- |
| `build_corpus.py` | Downloads 10 public-domain US government PDFs into `pdfs/` and writes `corpus/`: 11 test documents, 96 pages, plus `corpus/manifest.json`. Kinds: `text`, `scanned` (no text layer, skewed), `mixed` (first 3 pages scanned), `watermark` (diagonal CONFIDENTIAL + DRAFT footer), `deck` (chart pages as images, title only). |
| `build_golden.py` | Writes `golden.jsonl`: 150 questions, each with a short answer span checked verbatim against the ORIGINAL page text, plus doc, page and tag (`text` 105, `table` 11, `image` 20, `scanned` 14). Run with the main `.venv` (uses the app's LLM gateway, about $0.05). |
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

## Not done

- A scorer: retrieval recall@10 / budgeted recall per tag and per doc kind, pypdf vs the SHIPPED
  Docling parser (`ingest_worker.parsing.docling_pdf`, commit a08e6bb) with the shipped clean
  step and table chunks, plus watermark strings found in chunks. `evals/retrieval_eval.py` is the
  pattern to follow.
- More table questions (only 11; the pypdf text of tables is jumbled, so the question writer
  mostly chose prose). Figure-caption questions need Phase 3.
