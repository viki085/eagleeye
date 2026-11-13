-- Phase 4: text-to-SQL (C5) — data sources, role grants, semantic catalog, artifacts, audit log

create table data_sources (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    description text not null default '',
    engine text not null check (engine in ('postgres')),
    dsn_env text not null,              -- name of the env var holding the DSN (gateway only)
    status text not null default 'active' check (status in ('active', 'disabled')),
    schema_version integer not null default 0,
    max_rows integer not null default 10000,
    timeout_s integer not null default 15,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Phase 4 grants are per user role (groups arrive later, ADR-30).
create table source_grants (
    id uuid primary key default gen_random_uuid(),
    data_source_id uuid not null references data_sources (id) on delete cascade,
    role text not null check (role in ('member', 'knowledge_admin', 'data_admin', 'admin')),
    allowed_tables text[],              -- null = every enabled table
    can_see_pii boolean not null default false,
    unique (data_source_id, role)
);

create table catalog_tables (
    id uuid primary key default gen_random_uuid(),
    data_source_id uuid not null references data_sources (id) on delete cascade,
    schema_name text not null,
    table_name text not null,
    description text not null default '',
    row_estimate bigint,
    sensitivity text not null default 'internal'
        check (sensitivity in ('public', 'internal', 'restricted')),
    enabled boolean not null default false,
    embedding vector(1536),
    unique (data_source_id, schema_name, table_name)
);

create table catalog_columns (
    id uuid primary key default gen_random_uuid(),
    table_id uuid not null references catalog_tables (id) on delete cascade,
    name text not null,
    data_type text not null,
    description text not null default '',
    sample_values jsonb not null default '[]'::jsonb,
    is_pk boolean not null default false,
    fk_ref text,
    pii boolean not null default false,
    ordinal integer not null default 0,
    unique (table_id, name)
);

create table catalog_metrics (
    id uuid primary key default gen_random_uuid(),
    data_source_id uuid not null references data_sources (id) on delete cascade,
    name text not null,
    definition_sql text not null,
    description text not null default '',
    embedding vector(1536),
    unique (data_source_id, name)
);

create table catalog_examples (
    id uuid primary key default gen_random_uuid(),
    data_source_id uuid not null references data_sources (id) on delete cascade,
    question text not null,
    sql text not null,
    embedding vector(1536),
    unique (data_source_id, question)
);

create table artifacts (
    id uuid primary key,
    run_id uuid references runs (id) on delete set null,
    user_id uuid not null references users (id) on delete cascade,
    type text not null check (type in ('table', 'chart', 'profile')),
    title text not null,
    s3_key text not null,
    columns jsonb not null default '[]'::jsonb,
    row_count integer not null default 0,
    truncated boolean not null default false,
    source_refs jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
create index artifacts_user_idx on artifacts (user_id, created_at desc);

create table sql_query_log (
    id bigint generated always as identity primary key,
    run_id uuid references runs (id) on delete set null,
    user_id uuid references users (id) on delete set null,
    data_source_id uuid references data_sources (id) on delete set null,
    sql_hash text not null,
    sql_text text not null,
    rows integer,
    duration_ms integer,
    validated boolean not null,
    rejected_reason text,
    origin text not null check (origin in ('worker', 'gateway')),
    created_at timestamptz not null default now()
);
create index sql_query_log_created_idx on sql_query_log (created_at desc);
