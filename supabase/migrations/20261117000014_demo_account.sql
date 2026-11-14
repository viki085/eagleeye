-- Shared public demo account: flagged so the API can apply demo rules (own spend cap,
-- sign-in notifications, periodic reset) and the UI can show the demo banner and questions.
alter table users add column if not exists is_demo boolean not null default false;

-- Per-user lifetime LLM spend cap in USD; null = the organisation default (USAGE_LIMIT_USD).
alter table users add column if not exists usage_limit_usd numeric(10, 2)
    check (usage_limit_usd is null or usage_limit_usd >= 0);
