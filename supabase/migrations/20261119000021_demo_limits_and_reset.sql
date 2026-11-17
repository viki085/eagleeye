-- Demo limits raised, and an admin "reset" for a visit's allowance.
--
-- A visit's spend now counts from its window_start (the visit's start, or its last reset)
-- instead of over the visit account's whole life. Before any reset the two are the same, since
-- each visit has its own account. The admin console's reset sets window_start to now() and
-- seconds_used to 0, so the visit gets its full time, budget and notebook allowance back; its
-- chats stay. The shared daily total for all demo visitors is not changed by a reset.
-- Limits: visit budget USD 0.50 -> 1.00, daily total USD 2.00 -> 3.00 (never shown to visitors).

create or replace function demo_limits(
    out visit_seconds integer, out visit_budget_usd numeric, out daily_budget_usd numeric
)
language sql stable security definer set search_path = public as $$
    select
        coalesce((select (value #>> '{}')::integer from app_settings where key = 'demo_visit_seconds'), 1800),
        coalesce((select (value #>> '{}')::numeric from app_settings where key = 'demo_visit_budget_usd'), 1.00),
        coalesce((select (value #>> '{}')::numeric from app_settings where key = 'demo_daily_budget_usd'), 3.00)
$$;

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
    select coalesce(sum(cost_usd), 0) into spent
      from runs where user_id = v.user_id and created_at >= v.window_start;
    if v.seconds_used >= lim.visit_seconds or spent >= lim.visit_budget_usd then
        return jsonb_build_object(
            'allowed', false,
            'reason', case when v.seconds_used >= lim.visit_seconds then 'time' else 'budget' end,
            'available_at', v.window_start + interval '24 hours');
    end if;
    return jsonb_build_object('allowed', true, 'reason', null, 'available_at', null);
end
$$;

revoke all on function demo_limits() from public;
grant execute on function demo_limits() to service_role;
revoke all on function demo_gate(text) from public;
grant execute on function demo_gate(text) to anon, service_role;

-- Visits still open get the new budget (each visit account's lifetime cap is its budget).
update users u set usage_limit_usd = 1.00
  from demo_visits v
 where v.user_id = u.id and u.usage_limit_usd = 0.50
   and v.window_start > now() - interval '24 hours';
