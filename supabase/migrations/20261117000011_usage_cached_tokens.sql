-- Prompt caching: input tokens the provider served from its prompt cache (a subset of
-- tokens_in), recorded per LLM call so the admin console can show the cache hit rate.
alter table usage_ledger add column if not exists cached_tokens integer not null default 0;

-- the console's monthly spend reads the current calendar month
create index if not exists usage_ledger_created_idx on usage_ledger (created_at);
