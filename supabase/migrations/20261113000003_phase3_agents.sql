-- Phase 3: agent orchestration (C3) — routing metadata, steps, usage, security events

alter table runs drop constraint if exists runs_status_check;
alter table runs add constraint runs_status_check
    check (status in ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'BUDGET_EXCEEDED'));

alter table runs
    add column route text,
    add column guard jsonb,
    add column degraded boolean not null default false,
    add column heartbeat_at timestamptz,
    add column prompt_versions jsonb not null default '{}'::jsonb;

-- One active run per chat, enforced by the database (C3 §7).
create unique index runs_one_active_per_chat_uidx on runs (chat_id)
    where status in ('QUEUED', 'RUNNING');
create index runs_user_active_idx on runs (user_id) where status in ('QUEUED', 'RUNNING');

create table run_steps (
    id uuid primary key,
    run_id uuid not null references runs (id) on delete cascade,
    parent_step_id uuid,
    seq integer not null,
    kind text not null check (kind in ('guard', 'llm', 'tool', 'retrieval', 'check')),
    name text not null,
    input jsonb not null default '{}'::jsonb,
    output_summary text,
    status text not null check (status in ('ok', 'error', 'skipped')),
    duration_ms integer,
    tokens_in integer,
    tokens_out integer,
    cost_usd numeric(10, 6),
    created_at timestamptz not null default now()
);
create index run_steps_run_idx on run_steps (run_id, seq);

create table usage_ledger (
    id bigint generated always as identity primary key,
    user_id uuid not null references users (id) on delete cascade,
    run_id uuid references runs (id) on delete set null,
    model_id text not null,
    tokens_in integer not null default 0,
    tokens_out integer not null default 0,
    cost_usd numeric(10, 6) not null default 0,
    day date not null default current_date,
    created_at timestamptz not null default now()
);
create index usage_ledger_user_day_idx on usage_ledger (user_id, day);

-- Blocked inputs / filtered outputs, for review. Never shown to the user.
create table security_events (
    id bigint generated always as identity primary key,
    user_id uuid references users (id) on delete set null,
    run_id uuid references runs (id) on delete set null,
    kind text not null check (kind in ('input_blocked', 'output_filtered', 'guard_unavailable')),
    category text not null,
    detail jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
create index security_events_created_idx on security_events (created_at desc);
