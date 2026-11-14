"""Build the Grand Line data files used by the data-file analysis feature (CSV and XLSX).

  uv run --package eagleeye-datasets --with pandas==2.2.3 --with numpy==2.1.3 \
      python data/grandline/make_files.py

Most files are extracts or derivatives of the warehouse, so analysis results agree with SQL
answers. brent_crude_daily.csv is real public data (US EIA via FRED, public domain).
"""

import asyncio
import shutil
import sys
from pathlib import Path

import asyncpg
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "files"
ROOT = HERE.parents[1]
ADMIN_DSN = "postgresql://warehouse_admin:warehouse-local-admin@127.0.0.1:5433/warehouse"

QUERIES = {
    "voyage_utilisation_by_week.csv": """
        select date_trunc('week', v.departure_date)::date week_start, v.service_code, v.voyage_number,
               v.direction, vs.name vessel, vs.teu_capacity, e.teu_carried,
               round(e.teu_carried::numeric / vs.teu_capacity, 3) utilisation
        from operations.voyage_emissions e join network.voyages v using (voyage_id)
        join network.vessels vs using (vessel_id) order by 1, 2, 4""",
    "vessel_fuel_and_emissions.csv": """
        select v.voyage_number, vs.name vessel, vs.vessel_class, vs.fuel_type, v.routing,
               v.departure_date, e.distance_nm, e.avg_speed_knots, e.fuel_consumed_mt,
               e.co2_tonnes, e.teu_carried, e.co2_grams_per_teu_km, e.eu_ets_allowances
        from operations.voyage_emissions e join network.voyages v using (voyage_id)
        join network.vessels vs using (vessel_id) order by v.departure_date""",
    "port_congestion_weekly.csv": """
        select date_trunc('week', pc.scheduled_arrival)::date week_start, p.port_code, p.name port,
               count(*) calls,
               round(avg(extract(epoch from (pc.actual_arrival - pc.scheduled_arrival)) / 3600)::numeric, 1) avg_delay_hours,
               round(avg(extract(epoch from (pc.actual_departure - pc.actual_arrival)) / 3600)::numeric, 1) avg_hours_in_port
        from network.port_calls pc join network.ports p using (port_code)
        where pc.actual_arrival is not null and pc.seq > 1
        group by 1, 2, 3 order by 1, 2""",
    "bookings_extract_2026_q3.csv": """
        select b.booking_number, c.name customer, c.segment, c.country customer_country,
               b.service_code, b.origin_port, b.destination_port, b.cargo_ready_date,
               b.commodity, b.is_reefer, b.is_hazardous, b.container_count, b.teu,
               b.freight_revenue_usd, b.status, b.rolled_count,
               case when b.contract_id is null then 'spot' else 'contract' end pricing
        from commercial.bookings b join commercial.customers c using (customer_id)
        where b.cargo_ready_date between date '2026-07-01' and date '2026-09-30'
        order by b.cargo_ready_date, b.booking_number""",
}


async def extract() -> dict[str, pd.DataFrame]:
    conn = await asyncpg.connect(ADMIN_DSN)
    try:
        out = {}
        for name, sql in QUERIES.items():
            rows = await conn.fetch(sql)
            out[name] = pd.DataFrame([dict(r) for r in rows])
        out["_late"] = pd.DataFrame([dict(r) for r in await conn.fetch("""
            select b.booking_number, c.customer_id, c.name customer, c.segment, s.lane_code,
                   b.cargo_ready_date,
                   extract(epoch from (pc.actual_arrival - pc.scheduled_arrival)) / 3600 delay_hours
            from commercial.bookings b join commercial.customers c using (customer_id)
            join network.services s using (service_code)
            join network.port_calls pc on pc.voyage_id = b.voyage_id and pc.port_code = b.destination_port
            where b.status = 'delivered' and b.cargo_ready_date >= date '2026-01-01'
            order by b.booking_id""")])
        out["_subs"] = pd.DataFrame([dict(r) for r in await conn.fetch(
            "select subcontractor_id, name, service_type, country, performance_rating "
            "from operations.subcontractors order by subcontractor_id")])
        out["_lanes"] = pd.DataFrame([dict(r) for r in await conn.fetch("""
            select s.lane_code, date_trunc('month', b.cargo_ready_date)::date AS month, sum(b.teu) teu
            from commercial.bookings b join network.services s using (service_code)
            where b.status <> 'cancelled' and b.cargo_ready_date < date '2026-10-01'
            group by 1, 2 order by 1, 2""")])
        return out
    finally:
        await conn.close()


COMMENTS_GOOD = ("Smooth booking and on-time delivery.", "Customer service very responsive.",
                 "Good schedule reliability this quarter.", "Easy online booking.",
                 "Clear tracking updates throughout.")
COMMENTS_BAD = ("Vessel arrived several days late with little notice.",
                "Cargo was rolled to the next sailing during peak season.",
                "Invoice included demurrage we disputed.", "Hard to reach customer service.",
                "Tracking updates stopped mid-voyage.", "Rates too high compared with market.")


def survey(late: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    s = late.sample(n=min(50_000, len(late)), random_state=5).reset_index(drop=True)
    delay = s["delay_hours"].astype(float).clip(lower=0).fillna(0)
    base = 8.4 - 0.025 * delay + rng.normal(0, 1.4, len(s))
    nps = np.clip(np.rint(base), 0, 10).astype(int)
    comment = np.where(nps >= 8, rng.choice(COMMENTS_GOOD, len(s)),
                       np.where(nps <= 5, rng.choice(COMMENTS_BAD, len(s)), ""))
    comment = np.where(rng.random(len(s)) < 0.55, comment, "")
    return pd.DataFrame({
        "response_id": np.arange(1, len(s) + 1),
        "booking_number": s["booking_number"], "customer": s["customer"], "segment": s["segment"],
        "trade_lane": s["lane_code"],
        "response_date": pd.to_datetime(s["cargo_ready_date"]) + pd.to_timedelta(rng.integers(25, 60, len(s)), unit="D"),
        "likelihood_to_recommend_0_10": nps,
        "booking_ease_1_5": np.clip(np.rint(rng.normal(4.1, 0.7, len(s))), 1, 5).astype(int),
        "communication_1_5": np.clip(np.rint(3.9 - 0.006 * delay + rng.normal(0, 0.8, len(s))), 1, 5).astype(int),
        "comment": comment,
    })


def forecast(lanes: pd.DataFrame, rng: np.random.Generator, path: Path) -> None:
    growth = {"AEU": 0.03, "AMD": 0.025, "TPW": 0.02, "AUE": 0.035, "ECS": 0.05, "TAT": 0.01,
              "AMI": 0.06, "IAS": 0.04}
    months = pd.date_range("2027-01-01", "2027-12-01", freq="MS")
    frames = []
    for lane, g in lanes.groupby("lane_code"):
        recent = g[pd.to_datetime(g["month"]) >= "2025-10-01"]
        by_m = recent.assign(m=pd.to_datetime(recent["month"]).dt.month).groupby("m")["teu"].mean()
        base = np.array([float(by_m.get(m.month, by_m.mean())) for m in months]) * (1 + growth[lane])
        base = base * rng.normal(1, 0.02, len(base))
        frames.append(pd.DataFrame({"trade_lane": lane, "month": months.date,
                                    "base_teu": base.round(0), "low_teu": (base * 0.92).round(0),
                                    "high_teu": (base * 1.06).round(0)}))
    with pd.ExcelWriter(path) as xw:
        pd.concat(frames, ignore_index=True).to_excel(xw, sheet_name="Forecast", index=False)
        pd.DataFrame({"assumption": [
            "Base case: 2027 volume follows the recent seasonal pattern plus lane growth.",
            "High case: +6% on top of base; low case: -8% below base.",
            "Prepared by Commercial Planning, Grand Line Shipping Company, October 2026."]}
        ).to_excel(xw, sheet_name="Assumptions", index=False)


def scorecards(subs: pd.DataFrame, rng: np.random.Generator, path: Path) -> None:
    with pd.ExcelWriter(path) as xw:
        for q in ("Q1 2026", "Q2 2026", "Q3 2026"):
            df = subs.copy()
            r = df["performance_rating"].astype(float)
            df["on_time_pickup_pct"] = np.clip(r * 18 + rng.normal(5, 4, len(df)), 40, 100).round(1)
            df["damage_claims"] = rng.poisson(np.maximum(0.2, 5 - r))
            df["quarter_rating"] = np.clip(r + rng.normal(0, 0.25, len(df)), 1, 5).round(1)
            df.to_excel(xw, sheet_name=q, index=False)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(31)
    data = asyncio.run(extract())
    for name in QUERIES:
        data[name].to_csv(OUT / name, index=False)
    survey(data["_late"], rng).to_csv(OUT / "customer_survey_2026.csv", index=False)
    forecast(data["_lanes"], rng, OUT / "demand_forecast_2027_by_lane.xlsx")
    scorecards(data["_subs"], rng, OUT / "subcontractor_scorecards_2026.xlsx")
    brent = pd.read_csv(ROOT / "data" / "public" / "brent_daily_fred.csv", na_values=".")
    brent.columns = ["date", "brent_usd_per_barrel"]
    brent.dropna().to_csv(OUT / "brent_crude_daily.csv", index=False)
    shutil.copy(ROOT / "data" / "public" / "SOURCES.md", OUT / "SOURCES.md")
    for p in sorted(OUT.iterdir()):
        print(f"  {p.name:42} {p.stat().st_size / 1e6:6.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
