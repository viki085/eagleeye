-- Multimodal RAG plan, Phase 1: chunks record what kind of element they came from.
-- element_type: 'text' or 'table' now; 'image' arrives with figures (Phase 3, when asset_key
-- holds the figure's object-store key). bbox = position on the page in PDF points (left, top,
-- right, bottom). table_html = a table chunk's whole table, for showing it as a table.
alter table document_chunks
    add column element_type text not null default 'text'
        check (element_type in ('text', 'table', 'image')),
    add column bbox real[] check (bbox is null or cardinality(bbox) = 4),
    add column asset_key text,
    add column table_html text;

-- How a document was read: parser, OCR pages, low-confidence OCR pages, and the removed
-- watermark/header strings (the eval checks none of them reach a chunk).
alter table documents add column parse_report jsonb;
