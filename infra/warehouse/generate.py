"""Generate and load the Grand Line Shipping Company warehouse (fictional, deterministic).

Run from the repo root once the `warehouse` container is up:
  uv run --no-project --with numpy==2.1.3 --with pandas==2.2.3 --with faker==33.1.0 \
      --with asyncpg==0.30.0 python infra/warehouse/generate.py [--scale 0.1] [--if-empty]

--scale shrinks the cargo volume (bookings and everything derived from them) for quick tests.
--if-empty does nothing when the warehouse already holds data (used by the start script).
"""

import argparse
import asyncio
import io
import sys
import time
from pathlib import Path

import asyncpg
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from grandline import bookings, customers, equipment, finance, network, operations  # noqa: E402
from grandline import reference as ref  # noqa: E402

ADMIN_DSN = "postgresql://warehouse_admin:warehouse-local-admin@127.0.0.1:5433/warehouse"
SEED = 20240101
CHUNK = 250_000
INDEXES = (
    "create index on commercial.bookings (customer_id)",
    "create index on commercial.bookings (voyage_id)",
    "create index on commercial.bookings (booking_date)",
    "create index on commercial.bookings (service_code, booking_date)",
    "create index on commercial.booking_containers (container_number)",
    "create index on commercial.contracts (customer_id)",
    "create index on commercial.rate_cards (contract_id)",
    "create index on equipment.tracking_events (container_number, event_time)",
    "create index on equipment.tracking_events (booking_id)",
    "create index on finance.invoices (customer_id)",
    "create index on finance.invoices (booking_id)",
    "create index on finance.invoices (invoice_date)",
    "create index on finance.invoice_lines (charge_code)",
    "create index on finance.claims (booking_id)",
    "create index on finance.claims (filed_date)",
    "create index on network.port_calls (port_code)",
    "create index on network.voyages (service_code, departure_date)",
    "create index on operations.delay_incidents (voyage_id)",
    "create index on operations.delay_incidents (started_at)",
    "create index on operations.trucking_jobs (booking_id)",
)


def build(scale: float) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(SEED)
    t = time.monotonic()
    net = network.build(rng)
    employees = operations.build_employees(rng)
    com = customers.build(rng, len(employees))
    print(f"  network and customers ({time.monotonic() - t:.0f}s)", flush=True)
    bk = bookings.build(net, com, rng, scale)
    bk_df = bk.bookings.copy()
    bk_df["voyage_id"] = bk_df["voyage_id"].astype("Int64")
    print(f"  {len(bk_df):,} bookings ({time.monotonic() - t:.0f}s)", flush=True)
    bc, fleet = equipment.assign_containers(bk.containers, rng)
    events = equipment.tracking_events(bk_df, bc, rng)
    inv, lines = finance.build_invoices(bk_df, com.customers, rng)
    claims = finance.build_claims(bk_df, bc, fleet, rng)
    emissions = operations.build_emissions(net.voyages, net.vessels, bk_df)
    bunkers = finance.build_bunkers(net.voyages, emissions, net.vessels, rng)
    subs = operations.build_subcontractors(rng)
    trucks = operations.build_trucking(bk_df, subs, rng)
    warehouses, inventory = operations.build_warehouses_inventory(com.customers, rng)
    print(f"  everything else ({time.monotonic() - t:.0f}s)", flush=True)
    return {
        "network.trade_lanes": pd.DataFrame(ref.LANES, columns=["lane_code", "name"]),
        "network.ports": pd.DataFrame(ref.PORTS, columns=["port_code", "name", "country_code",
                                                          "country", "region", "latitude",
                                                          "longitude"]),
        "network.vessels": net.vessels,
        "network.services": _services(),
        "network.service_rotations": net.rotations,
        "network.voyages": net.voyages,
        "network.port_calls": _with_moves(net.port_calls, bk_df),
        "hr.employees": employees,
        "commercial.customers": com.customers,
        "commercial.contracts": com.contracts,
        "commercial.rate_cards": com.rate_cards,
        "commercial.bookings": bk_df,
        "equipment.containers": fleet,
        "commercial.booking_containers": bc,
        "equipment.tracking_events": events,
        "finance.invoices": inv,
        "finance.invoice_lines": lines,
        "finance.bunker_purchases": bunkers,
        "finance.claims": claims,
        "operations.delay_incidents": net.incidents,
        "operations.voyage_emissions": emissions,
        "operations.subcontractors": subs,
        "operations.trucking_jobs": trucks,
        "operations.warehouses": warehouses,
        "operations.inventory_snapshots": inventory,
    }


def _services() -> pd.DataFrame:
    return pd.DataFrame([{
        "service_code": s.code, "name": s.name, "lane_code": s.lane, "frequency_days": 7,
        "round_trip_days": s.vessels * 7, "nominal_vessel_teu": s.vessel_teu,
    } for s in ref.SERVICES])


def _with_moves(calls: pd.DataFrame, bk: pd.DataFrame) -> pd.DataFrame:
    live = bk[bk["status"] != "cancelled"]
    loads = live.groupby(["voyage_id", "origin_port"])["container_count"].sum()
    disch = live.groupby(["voyage_id", "destination_port"])["container_count"].sum()
    key = list(zip(calls["voyage_id"], calls["port_code"], strict=True))
    moves = np.array([loads.get(k, 0) + disch.get(k, 0) for k in key])
    calls = calls.copy()
    calls["container_moves"] = np.where(calls["actual_arrival"].notna(), moves, None)
    first = ~calls.duplicated(["voyage_id", "port_code"])
    calls.loc[~first, "container_moves"] = None
    return calls


async def _columns(conn: asyncpg.Connection, table: str) -> dict[str, str]:
    schema, name = table.split(".")
    rows = await conn.fetch(
        "select column_name, data_type from information_schema.columns where table_schema=$1 "
        "and table_name=$2 order by ordinal_position", schema, name)
    return {r["column_name"]: r["data_type"] for r in rows}


def _typed(df: pd.DataFrame, types: dict[str, str]) -> pd.DataFrame:
    """Integer columns that picked up NaN become floats in pandas; write them as integers."""
    out = df[list(types)].copy()
    for col, kind in types.items():
        if kind in ("integer", "bigint", "smallint"):
            out[col] = pd.to_numeric(out[col]).round().astype("Int64")
    return out


async def _copy(conn: asyncpg.Connection, table: str, df: pd.DataFrame) -> None:
    schema, name = table.split(".")
    types = await _columns(conn, table)
    cols = list(types)
    data = _typed(df, types)
    for start in range(0, len(data), CHUNK):
        buf = io.BytesIO()
        data.iloc[start:start + CHUNK].to_csv(buf, index=False, header=False)
        buf.seek(0)
        await conn.copy_to_table(name, source=buf, schema_name=schema, columns=cols, format="csv")


async def load(dsn: str, tables: dict[str, pd.DataFrame]) -> None:
    conn = await _connect(dsn)
    try:
        names = ", ".join(tables)
        await conn.execute(f"truncate {names} cascade")
        for table, df in tables.items():
            t = time.monotonic()
            await _copy(conn, table, df)
            print(f"  {table:34} {len(df):>10,} rows  {time.monotonic() - t:5.1f}s", flush=True)
        for stmt in INDEXES:
            await conn.execute(stmt)
        await conn.execute("analyze")
        size = await conn.fetchval("select pg_size_pretty(pg_database_size(current_database()))")
        print(f"  database size: {size}")
    finally:
        await conn.close()


async def _connect(dsn: str) -> asyncpg.Connection:
    for attempt in range(30):  # the container may still be starting
        try:
            return await asyncpg.connect(dsn)
        except (OSError, asyncpg.CannotConnectNowError):
            if attempt == 29:
                raise
            await asyncio.sleep(2)
    raise RuntimeError("unreachable")


async def is_loaded(dsn: str) -> bool:
    conn = await _connect(dsn)
    try:
        return bool(await conn.fetchval("select exists (select 1 from network.ports)"))
    finally:
        await conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dsn", default=ADMIN_DSN)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--if-empty", action="store_true")
    args = ap.parse_args()
    if args.if_empty and asyncio.run(is_loaded(args.dsn)):
        print("Grand Line warehouse already loaded; nothing to do.")
        return 0
    print(f"Generating Grand Line Shipping Company data (scale {args.scale})", flush=True)
    tables = build(args.scale)
    print("Loading into Postgres", flush=True)
    asyncio.run(load(args.dsn, tables))
    return 0


if __name__ == "__main__":
    sys.exit(main())
