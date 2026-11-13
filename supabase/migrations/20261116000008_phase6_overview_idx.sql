-- Phase 6A: the admin Overview filters usage_ledger by created_at (hourly cost buckets and
-- period comparisons); the existing index is on the day column only.

create index if not exists usage_ledger_created_idx on usage_ledger (created_at desc);
