-- Phase 1: identity + chat + runs (subset of docs/components/03-data-model.md)

create table users (
    id uuid primary key default gen_random_uuid(),
    clerk_user_id text unique not null,
    email text not null,
    display_name text,
    role text not null default 'member'
        check (role in ('member', 'knowledge_admin', 'data_admin', 'admin')),
    status text not null default 'active' check (status in ('active', 'disabled')),
    org_id text,
    last_seen_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table chats (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references users (id) on delete cascade,
    title text not null default 'New chat',
    last_message_no integer not null default 0,
    archived boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index chats_user_recent_idx on chats (user_id, updated_at desc);

create table runs (
    id uuid primary key default gen_random_uuid(),
    chat_id uuid not null references chats (id) on delete cascade,
    user_id uuid not null references users (id) on delete cascade,
    status text not null default 'QUEUED'
        check (status in ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
    model_ids jsonb not null default '{}'::jsonb,
    usage jsonb,
    cost_usd numeric(10, 6),
    error_code text,
    trace_id text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index runs_chat_idx on runs (chat_id, created_at desc);

create table messages (
    id uuid primary key default gen_random_uuid(),
    chat_id uuid not null references chats (id) on delete cascade,
    msg_no integer not null,
    role text not null check (role in ('user', 'assistant')),
    parts jsonb not null,
    run_id uuid references runs (id),
    idempotency_key text,
    tokens_in integer,
    tokens_out integer,
    created_at timestamptz not null default now(),
    unique (chat_id, msg_no),
    unique (chat_id, idempotency_key)
);

create index messages_chat_idx on messages (chat_id, msg_no);
