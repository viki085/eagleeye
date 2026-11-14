"""Facts pulled from the Grand Line warehouse, so every document agrees with the data."""

from dataclasses import dataclass
from datetime import date

import asyncpg

ADMIN_DSN = "postgresql://warehouse_admin:warehouse-local-admin@127.0.0.1:5433/warehouse"

ON_TIME = ("AVG(CASE WHEN pc.actual_arrival <= pc.scheduled_arrival + INTERVAL '24 hours' "
           "THEN 1.0 ELSE 0 END)")


@dataclass(frozen=True)
class Facts:
    months: list[dict]
    lanes_by_month: list[dict]
    incidents: list[dict]
    customers: list[dict]
    contracts: list[dict]
    rates: dict[int, list[dict]]
    ports: list[dict]
    subcontractors: list[dict]
    reefer_claims: list[dict]
    outage: list[dict]
    fleet: list[dict]
    quarters: list[dict]


async def _rows(conn: asyncpg.Connection, sql: str, *args) -> list[dict]:
    return [dict(r) for r in await conn.fetch(sql, *args)]


async def load(dsn: str = ADMIN_DSN) -> Facts:
    conn = await asyncpg.connect(dsn)
    try:
        return Facts(
            months=await _rows(conn, MONTHS),
            lanes_by_month=await _rows(conn, LANES_BY_MONTH),
            incidents=await _rows(conn, INCIDENTS),
            customers=await _rows(conn, CUSTOMERS),
            contracts=await _rows(conn, CONTRACTS),
            rates=await _rates(conn),
            ports=await _rows(conn, PORTS),
            subcontractors=await _rows(conn, SUBCONTRACTORS),
            reefer_claims=await _rows(conn, REEFER_CLAIMS),
            outage=await _rows(conn, OUTAGE),
            fleet=await _rows(conn, FLEET),
            quarters=await _rows(conn, QUARTERS),
        )
    finally:
        await conn.close()


async def _rates(conn: asyncpg.Connection) -> dict[int, list[dict]]:
    rows = await _rows(conn, """
        select r.contract_id, r.origin_port, r.destination_port, r.container_type, r.base_rate_usd
        from commercial.rate_cards r
        where r.contract_id = any($1::int[])
        order by r.contract_id, r.origin_port, r.destination_port, r.container_type""",
        [c["contract_id"] for c in await _rows(conn, CONTRACTS)])
    out: dict[int, list[dict]] = {}
    for r in rows:
        out.setdefault(r["contract_id"], []).append(r)
    return out


MONTHS = f"""
with b as (
  select date_trunc('month', cargo_ready_date)::date m, sum(teu) teu,
         sum(freight_revenue_usd) rev, count(*) bookings,
         count(*) filter (where rolled_count > 0) rolled
  from commercial.bookings where status <> 'cancelled' group by 1),
r as (
  select date_trunc('month', pc.scheduled_arrival)::date m, {ON_TIME} on_time
  from network.port_calls pc where pc.seq > 1 and pc.actual_arrival is not null group by 1),
i as (
  select date_trunc('month', started_at)::date m, count(*) incidents,
         count(*) filter (where severity in ('major', 'critical')) severe
  from operations.delay_incidents group by 1),
f as (
  select date_trunc('month', purchase_date)::date m,
         sum(price_usd_per_mt * quantity_mt) / sum(quantity_mt) fuel_price,
         sum(quantity_mt) fuel_mt
  from finance.bunker_purchases group by 1),
c as (
  select date_trunc('month', filed_date)::date m, count(*) claims,
         coalesce(sum(settled_amount_usd), 0) settled
  from finance.claims group by 1),
e as (
  select date_trunc('month', v.departure_date)::date m, sum(e.co2_tonnes) co2,
         sum(e.co2_tonnes) * 1e6 / nullif(sum(e.teu_carried * e.distance_nm * 1.852), 0) intensity
  from operations.voyage_emissions e join network.voyages v using (voyage_id) group by 1)
select b.m as month, b.teu, b.rev, b.bookings, b.rolled, r.on_time, i.incidents, i.severe,
       f.fuel_price, f.fuel_mt, c.claims, c.settled, e.co2, e.intensity
from b left join r using (m) left join i using (m) left join f using (m) left join c using (m)
left join e using (m)
where b.m between date '2024-01-01' and date '2026-10-01' order by 1
"""

LANES_BY_MONTH = f"""
with b as (
  select date_trunc('month', b.cargo_ready_date)::date m, s.lane_code, sum(b.teu) teu,
         sum(b.freight_revenue_usd) / sum(b.teu) rev_per_teu
  from commercial.bookings b join network.services s using (service_code)
  where b.status <> 'cancelled' group by 1, 2),
r as (
  select date_trunc('month', pc.scheduled_arrival)::date m, s.lane_code, {ON_TIME} on_time
  from network.port_calls pc join network.voyages v using (voyage_id)
  join network.services s using (service_code)
  where pc.seq > 1 and pc.actual_arrival is not null group by 1, 2)
select b.m as month, b.lane_code, b.teu, b.rev_per_teu, r.on_time
from b left join r using (m, lane_code)
where b.m between date '2024-01-01' and date '2026-10-01' order by 1, 2
"""

INCIDENTS = """
select d.incident_number, d.cause, d.severity, d.delay_hours, d.started_at, d.port_code,
       p.name port_name, v.voyage_number, v.service_code, vs.name vessel, v.routing,
       (select count(*) from commercial.bookings b where b.voyage_id = v.voyage_id
          and b.status <> 'cancelled') bookings_affected,
       (select coalesce(sum(b.teu), 0) from commercial.bookings b where b.voyage_id = v.voyage_id
          and b.status <> 'cancelled') teu_affected
from operations.delay_incidents d
join network.voyages v using (voyage_id)
join network.vessels vs using (vessel_id)
join network.ports p on p.port_code = d.port_code
where d.severity in ('major', 'critical') or d.cause in ('Labour strike', 'Red Sea diversion via Cape of Good Hope')
order by d.delay_hours desc
limit 140
"""

CUSTOMERS = """
select c.customer_id, c.name, c.industry, c.country, c.segment, c.payment_terms_days,
       c.credit_limit_usd, sum(b.teu) teu_2025, sum(b.freight_revenue_usd) rev_2025
from commercial.customers c join commercial.bookings b using (customer_id)
where b.status <> 'cancelled' and b.cargo_ready_date between date '2025-01-01' and date '2025-12-31'
group by c.customer_id order by rev_2025 desc limit 120
"""

CONTRACTS = """
select k.contract_id, k.contract_number, k.customer_id, c.name customer, c.country, k.lane_code,
       l.name lane_name, k.contract_type, k.start_date, k.end_date, k.committed_teu,
       c.payment_terms_days
from commercial.contracts k join commercial.customers c using (customer_id)
join network.trade_lanes l using (lane_code)
where k.start_date >= date '2025-01-01' and k.start_date < date '2026-01-01'
  and c.customer_id in (select customer_id from commercial.customers where segment = 'strategic')
order by c.customer_id, k.lane_code
limit 80
"""

PORTS = f"""
select p.port_code, p.name, p.country, p.region, count(*) calls,
       sum(pc.container_moves) moves, {ON_TIME} on_time,
       avg(extract(epoch from (pc.actual_departure - pc.actual_arrival)) / 3600) avg_port_hours,
       string_agg(distinct v.service_code, ', ') services
from network.port_calls pc join network.voyages v using (voyage_id)
join network.ports p on p.port_code = pc.port_code
where pc.actual_arrival is not null
group by p.port_code order by moves desc nulls last limit 40
"""

SUBCONTRACTORS = """
select s.subcontractor_id, s.name, s.service_type, s.country, s.performance_rating,
       count(t.job_id) jobs, avg(t.cost_usd) avg_cost
from operations.subcontractors s left join operations.trucking_jobs t using (subcontractor_id)
group by s.subcontractor_id order by jobs desc limit 30
"""

REEFER_CLAIMS = """
select date_trunc('month', filed_date)::date AS month, count(*) claims,
       count(*) filter (where root_cause like 'Faulty reefer controller%') controller_claims,
       coalesce(sum(settled_amount_usd), 0) settled
from finance.claims where claim_type = 'Reefer temperature deviation'
  and filed_date between date '2025-06-01' and date '2025-12-31' group by 1 order by 1
"""

OUTAGE = """
select booking_date, count(*) bookings from commercial.bookings
where booking_date between date '2025-06-03' and date '2025-06-24' group by 1 order by 1
"""

FLEET = """
select v.vessel_id, v.name, v.vessel_class, v.teu_capacity, v.ownership, v.fuel_type, v.built_year,
       v.daily_charter_cost_usd, v.in_fleet_from, v.in_fleet_to,
       (select service_code from network.voyages x where x.vessel_id = v.vessel_id
         group by service_code order by count(*) desc limit 1) service_code
from network.vessels v order by v.vessel_id
"""

QUARTERS = f"""
with b as (
  select date_trunc('quarter', cargo_ready_date)::date q, sum(teu) teu,
         sum(freight_revenue_usd) rev from commercial.bookings
  where status <> 'cancelled' group by 1),
r as (
  select date_trunc('quarter', pc.scheduled_arrival)::date q, {ON_TIME} on_time
  from network.port_calls pc where pc.seq > 1 and pc.actual_arrival is not null group by 1),
inv as (
  select date_trunc('quarter', invoice_date)::date q, sum(amount_usd) invoiced,
         sum(amount_usd) filter (where status in ('overdue', 'disputed')) at_risk
  from finance.invoices group by 1),
f as (
  select date_trunc('quarter', purchase_date)::date q, sum(price_usd_per_mt * quantity_mt) fuel_cost
  from finance.bunker_purchases group by 1),
e as (
  select date_trunc('quarter', v.departure_date)::date q, sum(e.co2_tonnes) co2,
         sum(e.eu_ets_allowances) ets
  from operations.voyage_emissions e join network.voyages v using (voyage_id) group by 1)
select b.q as quarter, b.teu, b.rev, r.on_time, inv.invoiced, inv.at_risk, f.fuel_cost, e.co2, e.ets
from b left join r using (q) left join inv using (q) left join f using (q) left join e using (q)
where b.q between date '2024-01-01' and date '2026-07-01' order by 1
"""


def quarter_label(d: date) -> str:
    return f"Q{(d.month - 1) // 3 + 1} {d.year}"
