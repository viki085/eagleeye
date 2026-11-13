-- Phase 6A: data for the admin console (exact timing + warnings per run) and indexes for
-- the console's time-range queries.

alter table runs
    add column first_token_at timestamptz,
    add column finished_at timestamptz,
    add column warnings text[] not null default '{}';

create index if not exists runs_created_idx on runs (created_at desc);
create index if not exists usage_ledger_day_idx on usage_ledger (day);
create index if not exists security_events_created_idx on security_events (created_at desc);
