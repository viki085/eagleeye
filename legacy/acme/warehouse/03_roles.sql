-- Read-only account used ONLY by the data gateway (C5 §5).
-- `sales` is exposed; `hr` is deliberately not granted (defence in depth behind sqlsafe).
-- Local demo password; real deployments take credentials from a secret manager.

create role eagleeye_ro login password 'eagleeye-ro-local';
alter role eagleeye_ro set default_transaction_read_only = on;
alter role eagleeye_ro set statement_timeout = '15s';
alter role eagleeye_ro set idle_in_transaction_session_timeout = '30s';

revoke all on schema public from public;
grant connect on database warehouse to eagleeye_ro;
grant usage on schema sales to eagleeye_ro;
grant select on all tables in schema sales to eagleeye_ro;
alter default privileges in schema sales grant select on tables to eagleeye_ro;
