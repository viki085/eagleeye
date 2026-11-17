-- Demo testers: networks whose demo visits have no time or budget limits.
--
-- The owner tests the public demo from their own connection, whose address changes within the
-- provider's range; listing that range (a CIDR) here keeps those visits from using up the
-- demo allowance, and their spending does not count toward the daily cap for everyone else.
-- Managed with scripts/demo_exempt.py; addresses are never committed to the repo.

create table if not exists demo_exempt_networks (
    network cidr primary key,
    note text not null default '',
    created_at timestamptz not null default now()
);
alter table demo_exempt_networks enable row level security;  -- server-side access only
revoke all on demo_exempt_networks from anon, authenticated;

alter table demo_visits add column if not exists exempt boolean not null default false;

-- Is this visitor address on the exempt list? (The same address key as the visits use.)
create or replace function demo_exempt(ip text) returns boolean
language plpgsql stable security definer set search_path = public as $$
begin
    return exists (
        select 1 from demo_exempt_networks n where demo_ip_key(ip)::inet <<= n.network
    );
exception when others then
    return false;  -- an unparsable address is never exempt
end
$$;

-- The gate, as in migration 16, plus: exempt networks are always let in, and exempt visits'
-- spending is left out of the daily cap.
create or replace function demo_gate(ip text) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
    lim record;
    v demo_visits%rowtype;
    spent numeric;
    today numeric;
begin
    if demo_exempt(ip) then
        return jsonb_build_object('allowed', true, 'reason', null, 'available_at', null);
    end if;
    select * into lim from demo_limits();
    select coalesce(sum(r.cost_usd), 0) into today
      from runs r join users u on u.id = r.user_id
     where u.is_demo and r.created_at >= date_trunc('day', now() at time zone 'utc') at time zone 'utc'
       and not exists (select 1 from demo_visits ev where ev.user_id = u.id and ev.exempt);
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

revoke all on function demo_exempt(text) from public, anon, authenticated;
grant execute on function demo_exempt(text) to service_role;
revoke all on function demo_gate(text) from public;
grant execute on function demo_gate(text) to anon, service_role;
