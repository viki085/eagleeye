-- Undo migration 19 (demo tester networks): the owner chose to reset a used-up visit when
-- needed instead. The gate goes back to migration 16's definition.

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
grant execute on function demo_gate(text) to anon, service_role;

drop function if exists demo_exempt(text);
alter table demo_visits drop column if exists exempt;
drop table if exists demo_exempt_networks;
