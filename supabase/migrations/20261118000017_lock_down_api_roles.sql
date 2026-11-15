-- Close Supabase's REST API (Phase 7B security review).
--
-- EagleEye's services connect as the database owner; nothing uses Supabase's REST API except the
-- /demo sign-in, which calls one function, demo_gate(ip). But Supabase's default privileges give
-- its API roles (anon, authenticated) access to every new table, sequence and function in
-- `public`, so on a hosted project anyone holding the project URL and its public anon key could
-- read chats, users and files' metadata. This takes all of that away, turns on row-level
-- security everywhere as a second wall (the owner the app connects as is not affected), and
-- leaves exactly one door: demo_gate.

do $$
declare
    t record;
begin
    for t in
        select c.oid::regclass as tbl
          from pg_class c join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public' and c.relkind in ('r', 'p')
    loop
        execute format('alter table %s enable row level security', t.tbl);
    end loop;
end $$;

revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;

-- EagleEye's own functions only: extension functions (pgvector's) belong to the extension
do $$
declare
    f record;
begin
    for f in
        select p.oid::regprocedure as fn
          from pg_proc p join pg_namespace n on n.oid = p.pronamespace
         where n.nspname = 'public'
           and not exists (
               select 1 from pg_depend d
                where d.classid = 'pg_proc'::regclass and d.objid = p.oid and d.deptype = 'e'
           )
    loop
        execute format('revoke all on function %s from public, anon, authenticated', f.fn);
    end loop;
end $$;

-- the one door: allowed / reason / when for an IP, never visit data (security definer)
grant execute on function demo_gate(text) to anon, service_role;
grant execute on function demo_limits() to service_role;

-- and nothing created later gets the API roles by default
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges in schema public revoke all on functions from public, anon, authenticated;
