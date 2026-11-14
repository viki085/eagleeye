-- Read-only account used ONLY by the data gateway (C5 §5).
-- The catalog decides which roles may query which tables (hr is for data admins only);
-- this account is the database-level backstop: read-only, time-limited.
-- Local demo password; cloud deployments take credentials from the secret store.

create role eagleeye_ro login password 'eagleeye-ro-local';
alter role eagleeye_ro set default_transaction_read_only = on;
alter role eagleeye_ro set statement_timeout = '15s';
alter role eagleeye_ro set idle_in_transaction_session_timeout = '30s';

revoke all on schema public from public;
grant connect on database warehouse to eagleeye_ro;

do $$
declare s text;
begin
    foreach s in array array['network', 'commercial', 'equipment', 'finance', 'operations', 'hr'] loop
        execute format('grant usage on schema %I to eagleeye_ro', s);
        execute format('grant select on all tables in schema %I to eagleeye_ro', s);
        execute format('alter default privileges in schema %I grant select on tables to eagleeye_ro', s);
    end loop;
end $$;
