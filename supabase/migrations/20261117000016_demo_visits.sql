-- Demo visitor allowances (Phase 7, docs/phase7-cloud-plan.md "Demo access").
--
-- Everyone signs in with the shared demo credentials, but each VISIT gets its own internal
-- EagleEye account (users.is_demo, a synthetic clerk_user_id). All per-user isolation (chats,
-- documents, data files, results, notebooks, document search) therefore applies between
-- visitors unchanged, and the visit's budget is that account's usage_limit_usd.
--
-- A visit belongs to one IP (IPv6: its /64) for 24 hours from its first sign-in: 30 minutes of
-- use (counted while the app is open) and $0.50 of AI answers. Signing in again within the
-- window resumes the same visit. All demo visits together: $2 per UTC day.

create table if not exists demo_visits (
    id uuid primary key default gen_random_uuid(),
    ip_key text not null,
    user_id uuid not null unique references users (id) on delete cascade,
    window_start timestamptz not null default now(),
    seconds_used integer not null default 0 check (seconds_used >= 0),
    created_at timestamptz not null default now()
);
create index if not exists demo_visits_ip_idx on demo_visits (ip_key, window_start desc);

-- One row per Clerk sign-in session; heartbeats from the open app add up the visit's time.
create table if not exists demo_sessions (
    clerk_session_id text primary key,
    visit_id uuid not null references demo_visits (id) on delete cascade,
    last_seen_at timestamptz not null default now(),
    created_at timestamptz not null default now()
);

alter table demo_visits enable row level security;  -- server-side access only
alter table demo_sessions enable row level security;

-- The limits, in one place. Admins may override them through app_settings.
create or replace function demo_limits(
    out visit_seconds integer, out visit_budget_usd numeric, out daily_budget_usd numeric
)
language sql stable security definer set search_path = public as $$
    select
        coalesce((select (value #>> '{}')::integer from app_settings where key = 'demo_visit_seconds'), 1800),
        coalesce((select (value #>> '{}')::numeric from app_settings where key = 'demo_visit_budget_usd'), 0.50),
        coalesce((select (value #>> '{}')::numeric from app_settings where key = 'demo_daily_budget_usd'), 2.00)
$$;

-- An IP -> the visitor key: IPv4 as is; IPv6 grouped by /64 (addresses rotate within it).
-- IPv4-mapped IPv6 (::ffff:a.b.c.d, how dual-stack servers report IPv4 clients) is its IPv4
-- address, and IPv6 loopback is IPv4 loopback, so every front end yields the same key.
create or replace function demo_ip_key(ip text) returns text
language plpgsql immutable as $$
declare
    addr inet;
begin
    addr := trim(ip)::inet;
    if family(addr) = 6 and host(addr) ~* '^::ffff:\d+\.\d+\.\d+\.\d+$' then
        return substring(host(addr) from 8);
    end if;
    if addr = '::1'::inet then
        return '127.0.0.1';
    end if;
    if family(addr) = 6 then
        return network(set_masklen(addr, 64))::text;
    end if;
    return host(addr);
exception when others then
    return 'unknown:' || left(coalesce(ip, ''), 64);
end
$$;

-- The gate the /demo sign-in (and the wake route) asks before letting a visitor in. It
-- reveals only allowed / reason / when, never visit data. Callable by the anon role, which
-- cannot read the tables themselves.
create or replace function demo_gate(ip text) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
    lim record;
    v demo_visits%rowtype;
    spent numeric;
    today numeric;
begin
    select * into lim from demo_limits();
    select coalesce(sum(r.cost_usd), 0) into today
      from runs r join users u on u.id = r.user_id
     where u.is_demo and r.created_at >= date_trunc('day', now() at time zone 'utc') at time zone 'utc';
    if today >= lim.daily_budget_usd then
        return jsonb_build_object(
            'allowed', false, 'reason', 'daily',
            'available_at', (date_trunc('day', now() at time zone 'utc') + interval '1 day') at time zone 'utc');
    end if;
    select * into v from demo_visits
     where ip_key = demo_ip_key(ip) and window_start > now() - interval '24 hours'
     order by window_start desc limit 1;
    if not found then
        return jsonb_build_object('allowed', true, 'reason', null, 'available_at', null);
    end if;
    select coalesce(sum(cost_usd), 0) into spent from runs where user_id = v.user_id;
    if v.seconds_used >= lim.visit_seconds or spent >= lim.visit_budget_usd then
        return jsonb_build_object(
            'allowed', false,
            'reason', case when v.seconds_used >= lim.visit_seconds then 'time' else 'budget' end,
            'available_at', v.window_start + interval '24 hours');
    end if;
    return jsonb_build_object('allowed', true, 'reason', null, 'available_at', null);
end
$$;

revoke all on function demo_gate(text) from public;
revoke all on function demo_limits() from public;
grant execute on function demo_gate(text) to anon, service_role;
grant execute on function demo_limits() to service_role;

-- belt and braces: the API roles never touch these tables directly (RLS already returns nothing)
revoke all on demo_visits, demo_sessions from anon, authenticated;
