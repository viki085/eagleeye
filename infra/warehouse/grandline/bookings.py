"""Bookings and booking containers, filled voyage by voyage up to each vessel's capacity."""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from grandline import markets
from grandline import reference as ref
from grandline.customers import lane_ports

TYPE_P = {"20DV": 0.22, "40DV": 0.15, "40HC": 0.55, "20TK": 0.0, "40OT": 0.02,
          "20RF": 0.0, "40RF": 0.0}
COUNTS = np.array([1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 30, 40])
COUNT_P = np.array([30, 21, 12, 9, 6, 5, 4, 3, 3, 2, 2, 2, 1], dtype=float)
COUNT_P /= COUNT_P.sum()


@dataclass(frozen=True)
class Bookings:
    bookings: pd.DataFrame
    containers: pd.DataFrame  # booking_containers


LANE_LOAD = {"AEU": 0.84, "AMD": 0.82, "TPW": 0.87, "AUE": 0.83, "ECS": 0.78, "TAT": 0.74,
             "AMI": 0.80, "IAS": 0.72}
BACKHAUL_LOAD = {"AEU": 0.33, "AMD": 0.36, "TPW": 0.30, "AUE": 0.32, "ECS": 0.45, "TAT": 0.62,
                 "AMI": 0.40, "IAS": 0.60}


def _utilisation(day: date, headhaul: bool, lane: str, rng: np.random.Generator) -> float:
    noise = float(rng.lognormal(0, 0.07))
    if not headhaul:
        return min(BACKHAUL_LOAD[lane] * noise, 0.95)
    u = LANE_LOAD[lane]
    if day.month in (8, 9, 10):
        u += 0.10  # peak season
    if day.month == 2:
        u -= 0.18  # Lunar New Year factory closures
    if lane in ("AEU", "AMD") and date(2024, 3, 1) <= day <= date(2024, 9, 30):
        u += 0.08  # Red Sea capacity squeeze
    if date(2026, 1, 1) <= day:
        u -= 0.06  # new vessels delivered across the industry: softer demand per ship
    return min(u * noise, 0.99)


def _call_times(port_calls: pd.DataFrame) -> dict[tuple[int, str], tuple]:
    first = port_calls.drop_duplicates(["voyage_id", "port_code"])
    return {(r.voyage_id, r.port_code): (r.scheduled_arrival, r.actual_arrival, r.actual_departure)
            for r in first.itertuples(index=False)}


def _customer_pools(customers: pd.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    pools = {}
    for region, g in customers.groupby("home_region"):
        w = g["volume_weight"].to_numpy()
        pools[region] = (g["customer_id"].to_numpy(), w / w.sum())
    return pools


def _commodities(rng: np.random.Generator, n: int):
    w = np.array([c[3] for c in ref.COMMODITIES], dtype=float)
    idx = rng.choice(len(ref.COMMODITIES), size=n, p=w / w.sum())
    names = np.array([c[0] for c in ref.COMMODITIES])[idx]
    reefer = np.array([c[1] for c in ref.COMMODITIES])[idx]
    dg = np.array([c[2] for c in ref.COMMODITIES])[idx]
    return names, reefer, dg


def _types(rng: np.random.Generator, names: np.ndarray, reefer: np.ndarray) -> np.ndarray:
    keys = list(TYPE_P)
    p = np.array([TYPE_P[k] for k in keys])
    out = rng.choice(keys, size=len(names), p=p / p.sum())
    out = np.where(reefer, np.where(rng.random(len(names)) < 0.85, "40RF", "20RF"), out)
    tank = (names == "Industrial chemicals") & (rng.random(len(names)) < 0.5)
    return np.where(tank, "20TK", out)


def build(network, commercial, rng: np.random.Generator, scale: float = 1.0) -> Bookings:
    services = {s.code: s for s in ref.SERVICES}
    vessels = network.vessels.set_index("vessel_id")["teu_capacity"].to_dict()
    calls = _call_times(network.port_calls)
    ports = lane_ports()
    pools = _customer_pools(commercial.customers)
    segment = commercial.customers.set_index("customer_id")["segment"].to_dict()
    contracts = _contract_index(commercial.contracts)
    cards = {(r.contract_id, r.origin_port, r.destination_port, r.container_type): r.base_rate_usd
             for r in commercial.rate_cards.itertuples(index=False)}
    frames = []
    for v in network.voyages.itertuples(index=False):
        s = services[v.service_code]
        headhaul = v.direction == "headhaul"
        target_teu = vessels[v.vessel_id] * _utilisation(v.departure_date, headhaul, s.lane, rng) * scale
        if target_teu < 1:
            continue
        frames.append(_voyage_bookings(v, s, headhaul, target_teu, ports, pools, calls, rng))
    df = pd.concat(frames, ignore_index=True)
    df = _assign_contracts_and_revenue(df, contracts, cards, segment, rng)
    df = _apply_events(df, rng)
    df.insert(0, "booking_id", np.arange(1, len(df) + 1))
    years = pd.to_datetime(df["booking_date"]).dt.year.to_numpy() % 100
    df.insert(1, "booking_number", [f"GLS{y:02d}{i:07d}" for y, i in zip(years, df["booking_id"])])
    containers = _booking_containers(df, rng)
    return Bookings(df, containers)


def _voyage_bookings(v, s, headhaul, target_teu, ports, pools, calls, rng) -> pd.DataFrame:
    origins, dests = ports[(s.code, v.direction)]
    est = int(target_teu / 5.5 * 1.3) + 5
    counts = rng.choice(COUNTS, size=est, p=COUNT_P)
    names, reefer, dg = _commodities(rng, est)
    types = _types(rng, names, reefer)
    teu = counts * np.vectorize(ref.CONTAINER_TEU.get)(types)
    keep = np.cumsum(teu) <= target_teu
    keep[0] = True
    n = int(keep.sum())
    o = rng.choice(origins, size=n, p=_front_weights(len(origins)))
    d = rng.choice(dests, size=n)
    region_o = ref.PORT_REGION[origins[0]]
    region_d = ref.PORT_REGION[dests[-1]]
    from_origin = rng.random(n) < 0.6
    cust = np.empty(n, dtype=np.int64)
    for region, mask in ((region_o, from_origin), (region_d, ~from_origin)):
        ids, p = pools.get(region, pools["Asia"])
        cust[mask] = rng.choice(ids, size=int(mask.sum()), p=p)
    dep = pd.DatetimeIndex([_departure(calls, v, port) for port in o])
    ready = dep - pd.to_timedelta(rng.integers(1, 6, n), unit="D")
    lead = np.clip(rng.gamma(2.0, 9.0, n), 2, 70).astype(int)
    return pd.DataFrame({
        "customer_id": cust, "voyage_id": v.voyage_id, "service_code": s.code,
        "lane": s.lane, "headhaul": headhaul, "routing": v.routing,
        "origin_port": o, "destination_port": d,
        "departure": dep, "arrival": [_arrival(calls, v, port) for port in d],
        "booking_date": (ready - pd.to_timedelta(lead, unit="D")).date,
        "cargo_ready_date": ready.date,
        "commodity": names[:n], "is_reefer": reefer[:n], "is_hazardous": dg[:n],
        "container_type": types[:n], "container_count": counts[:n], "teu": teu[:n],
        "incoterm": rng.choice(ref.INCOTERMS, size=n, p=[0.34, 0.2, 0.1, 0.1, 0.12, 0.06, 0.08]),
    })


def _front_weights(n: int) -> np.ndarray:
    w = 1.0 / np.arange(1, n + 1) ** 0.4
    return w / w.sum()


def _departure(calls, v, port) -> pd.Timestamp:
    sched, actual, act_dep = calls[(v.voyage_id, port)]
    return pd.Timestamp(act_dep if act_dep is not None and not pd.isna(act_dep) else sched)


def _arrival(calls, v, port):
    sched, actual, _ = calls[(v.voyage_id, port)]
    return actual if actual is not None and not pd.isna(actual) else None


def _contract_index(contracts: pd.DataFrame) -> dict[tuple[int, str], list[tuple]]:
    idx: dict[tuple[int, str], list[tuple]] = {}
    for r in contracts.itertuples(index=False):
        idx.setdefault((r.customer_id, r.lane_code), []).append((r.start_date, r.end_date, r.contract_id))
    return idx


def _assign_contracts_and_revenue(df, contracts, cards, segment, rng) -> pd.DataFrame:
    contract_ids, rates = [], []
    spot = np.zeros(len(df))
    for lane, g in df.groupby("lane"):
        days = pd.to_datetime(g["cargo_ready_date"]).to_numpy().astype("datetime64[D]")
        spot[g.index] = markets.spot_rates(lane, days)
    size = np.vectorize(markets.SIZE_FACTOR.get)(df["container_type"].to_numpy())
    ratio = np.vectorize(markets.BACKHAUL_RATIO.get)(df["lane"].to_numpy())
    spot = spot * size * np.where(df["headhaul"], 1.0, ratio) * rng.lognormal(0, 0.1, len(df))
    for i, r in enumerate(df.itertuples(index=False)):
        cid, rate = None, None
        for start, end, c in contracts.get((r.customer_id, r.lane), ()):
            if start <= r.cargo_ready_date <= end:
                key_type = r.container_type if r.container_type in ("20DV", "40DV", "40HC", "40RF") else "40HC"
                rate = cards.get((c, r.origin_port, r.destination_port, key_type))
                if rate is not None:
                    cid = c
                break
        contract_ids.append(cid)
        rates.append(rate if rate is not None else spot[i] * 1.06)
    df["contract_id"] = pd.array(contract_ids, dtype="Int64")
    df["rate_per_container"] = np.round(np.array(rates, dtype=float), 2)
    df["freight_revenue_usd"] = np.round(df["rate_per_container"] * df["container_count"], 2)
    return df


def _apply_events(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    lo, hi = ref.CYBER_OUTAGE
    bd = df["booking_date"]
    hit = (bd >= lo) & (bd <= hi)
    df.loc[hit, "booking_date"] = [hi + timedelta(days=int(x)) for x in rng.integers(1, 4, hit.sum())]
    df["booking_date"] = np.minimum(df["booking_date"], df["cargo_ready_date"])
    squeeze = df["lane"].isin(["AEU", "AMD"]) & df["headhaul"] & df["cargo_ready_date"].between(
        date(2024, 4, 1), date(2024, 9, 30))
    p_roll = np.where(squeeze, 0.14, 0.04)
    df["rolled_count"] = (rng.random(len(df)) < p_roll).astype(int)
    today = pd.Timestamp(ref.END + timedelta(days=14), tz="UTC")
    cancelled = rng.random(len(df)) < 0.035
    arrived = df["arrival"].notna() & (pd.to_datetime(df["arrival"], utc=True) < today)
    departed = pd.to_datetime(df["departure"], utc=True) < today
    df["status"] = np.select([cancelled, arrived, departed], ["cancelled", "delivered", "shipped"],
                             "confirmed")
    df.loc[cancelled, "voyage_id"] = None
    return df


def _booking_containers(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    rep = df.loc[df.index.repeat(df["container_count"])]
    n = len(rep)
    reefer = rep["container_type"].str.endswith("RF").to_numpy()
    teu = np.vectorize(ref.CONTAINER_TEU.get)(rep["container_type"].to_numpy())
    weight = np.where(teu == 1, rng.normal(17500, 4500, n), rng.normal(13500, 5000, n))
    seal = np.char.add("GL", rng.integers(10_000_000, 99_999_999, n).astype(str)).astype(object)
    seal[rng.random(n) < 0.012] = None  # missing seal numbers: a known data-quality issue
    setpoint = np.where(reefer, rng.choice([-25.0, -18.0, 2.0, 4.0, 13.0], n), np.nan)
    return pd.DataFrame({
        "booking_id": rep["booking_id"].to_numpy(),
        "container_type": rep["container_type"].to_numpy(),
        "gross_weight_kg": np.clip(weight, 2500, 30480).astype(int),
        "seal_number": seal,
        "vgm_submitted": rng.random(n) > 0.004,
        "temperature_setpoint_c": setpoint,
        "_ready": rep["cargo_ready_date"].to_numpy(),
        "_arrival": rep["arrival"].to_numpy(),
        "_status": rep["status"].to_numpy(),
    })
