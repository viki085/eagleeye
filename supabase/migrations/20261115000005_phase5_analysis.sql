-- Phase 5: data files, analysis sandbox, charts (C6)

-- A dataset is a Parquet file in the object store plus its schema and profile.
-- One uploaded file gives one dataset (CSV/TSV) or one per sheet (XLSX).
create table datasets (
    id uuid primary key,
    owner_id uuid not null references users (id) on delete cascade,
    origin text not null check (origin in ('csv_upload', 'xlsx')),
    title text not null,
    filename text not null,
    sheet text not null default '',          -- XLSX sheet name; '' for CSV/TSV
    s3_key_original text not null,
    s3_key text not null default '',         -- Parquet; set when READY
    status text not null default 'UPLOADED'
        check (status in ('UPLOADED', 'PROFILING', 'READY', 'FAILED')),
    error text,
    columns jsonb not null default '[]'::jsonb,     -- [{name, type}]
    column_map jsonb not null default '{}'::jsonb,  -- safe name -> original header
    row_count integer not null default 0,
    size_bytes bigint not null default 0,
    sha256 text not null,
    profile jsonb not null default '{}'::jsonb,
    summary text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (owner_id, sha256, sheet)
);
create index datasets_owner_idx on datasets (owner_id, created_at desc);

-- Every sandbox execution: audit trail and the source of the per-user hourly limit.
create table sandbox_runs (
    id bigint generated always as identity primary key,
    run_id uuid references runs (id) on delete set null,
    user_id uuid not null references users (id) on delete cascade,
    mode text not null check (mode in ('sql', 'python')),
    code_hash text not null,
    code_text text not null,
    status text not null check (status in ('ok', 'error', 'timeout', 'rejected')),
    duration_ms integer not null default 0,
    error text,
    created_at timestamptz not null default now()
);
create index sandbox_runs_user_idx on sandbox_runs (user_id, created_at desc);
