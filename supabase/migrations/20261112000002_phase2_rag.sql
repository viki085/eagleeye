-- Phase 2: documents + chunks (C4 dual-store: personal embeddings here, enterprise in Qdrant)

create extension if not exists vector;

create table documents (
    id uuid primary key default gen_random_uuid(),
    scope text not null check (scope in ('enterprise', 'personal')),
    owner_id uuid references users (id) on delete cascade,
    uploaded_by uuid not null references users (id) on delete cascade,
    title text not null,
    filename text not null,
    mime text not null,
    size_bytes bigint not null,
    sha256 text not null,
    s3_key text not null,
    status text not null default 'UPLOADING'
        check (status in ('UPLOADING', 'SCANNING', 'PARSING', 'CHUNKING', 'EMBEDDING',
                          'READY', 'FAILED')),
    error text,
    page_count integer,
    chunk_count integer,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint personal_has_owner check (scope = 'enterprise' or owner_id is not null),
    constraint enterprise_has_no_owner check (scope = 'personal' or owner_id is null)
);

-- Dedup: a NULL owner would defeat a plain unique(sha256, owner_id), so split by scope.
create unique index documents_enterprise_sha_uidx on documents (sha256)
    where scope = 'enterprise';
create unique index documents_personal_sha_uidx on documents (sha256, owner_id)
    where scope = 'personal';

create index documents_owner_idx on documents (owner_id, created_at desc);
create index documents_scope_idx on documents (scope, status);

-- Dimension matches EMBED_DIM (default text-embedding-3-small @ 1536).
-- Embedding column is populated for personal scope only; enterprise vectors live in Qdrant.
create table document_chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references documents (id) on delete cascade,
    chunk_no integer not null,
    content text not null,
    heading_path text[] not null default '{}',
    page integer,
    scope text not null check (scope in ('enterprise', 'personal')),
    owner_id uuid,
    chunk_hash text not null,
    embedding vector(1536),
    tsv tsvector generated always as (to_tsvector('english', content)) stored,
    created_at timestamptz not null default now(),
    unique (document_id, chunk_no)
);

create index chunks_doc_idx on document_chunks (document_id, chunk_no);
create index chunks_scope_owner_idx on document_chunks (scope, owner_id);
create index chunks_tsv_idx on document_chunks using gin (tsv);
create index chunks_personal_hnsw_idx on document_chunks
    using hnsw (embedding vector_cosine_ops)
    with (m = 16, ef_construction = 128)
    where scope = 'personal';

alter table runs add column params jsonb not null default '{}'::jsonb;
