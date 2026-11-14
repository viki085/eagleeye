"""Vessels, voyages, port calls and delay incidents.

Delays are built from named causes so the incident log, the port-call times and the
investigation reports all tell the same story (Red Sea diversion, congestion, strike, weather).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

import numpy as np
import pandas as pd

from grandline import reference as ref

VESSEL_WORDS = (
    "Aurora", "Boreas", "Calypso", "Dauntless", "Equinox", "Falcon", "Galene", "Halcyon",
    "Indigo", "Juniper", "Kestrel", "Lodestar", "Mariner", "Nautilus", "Orion", "Pegasus",
    "Quasar", "Resolute", "Sirius", "Tempest", "Ulysses", "Vega", "Wayfarer", "Xanthe",
    "Zephyr", "Altair", "Borealis", "Corsair", "Delphine", "Endeavour", "Fortuna", "Gallant",
    "Horizon", "Intrepid", "Jubilee", "Liberty", "Monsoon", "Neptune", "Odyssey", "Polaris",
    "Radiant", "Solstice", "Trident", "Valiant", "Windward", "Arcadia", "Bellatrix", "Celestine",
    "Dawnstar", "Eclipse", "Fairwind", "Glacier", "Harbinger", "Isla Verde", "Kingfisher",
    "Larkspur", "Meridian", "Northstar", "Oceanus", "Pioneer", "Saltmarsh", "Tidewater",
    "Seabright", "Starling", "Coral Bay", "Silver Reef", "Bluewater", "Cape Verity",
)
FLAGS = ("Liberia", "Marshall Islands", "Panama", "Singapore", "Malta", "Netherlands")
CHARTER_DAY_RATE = {1700: 16_000, 3500: 24_000, 4500: 30_000, 4800: 31_000, 5500: 36_000,
                    6000: 40_000, 6500: 44_000, 8500: 58_000}


@dataclass(frozen=True)
class Network:
    vessels: pd.DataFrame
    rotations: pd.DataFrame
    voyages: pd.DataFrame
    port_calls: pd.DataFrame
    incidents: pd.DataFrame


def _imo(rng: np.random.Generator, used: set[str]) -> str:
    while True:
        base = rng.integers(970_000, 999_999)
        digits = [int(c) for c in str(base)]
        check = sum(d * w for d, w in zip(digits, range(7, 1, -1), strict=True)) % 10
        imo = f"{base}{check}"
        if imo not in used:
            used.add(imo)
            return imo


def _vessel_class(teu: int) -> str:
    if teu < 3000:
        return "Feeder"
    if teu < 5100:
        return "Panamax"
    if teu < 7000:
        return "Post-Panamax"
    return "Neo-Panamax"


def build_vessels(rng: np.random.Generator) -> pd.DataFrame:
    rows, used, n = [], set(), 0
    plan = [(s.code, s.vessel_teu, s.vessels, None, None) for s in ref.SERVICES]
    # extra chartered tonnage to keep weekly schedules while sailing round the Cape
    plan += [("AEX", 8500, 2, date(2024, 1, 15), date(2025, 7, 31)),
             ("AMX", 6500, 2, date(2024, 1, 15), date(2025, 7, 31))]
    for service, teu, count, start, end in plan:
        for _ in range(count):
            n += 1
            size = int(teu * rng.uniform(0.94, 1.06) // 50 * 50)
            chartered = start is not None or rng.random() < 0.45
            built = int(rng.integers(2006, 2026)) if start is None else int(rng.integers(2008, 2016))
            fuel = ("LNG dual-fuel" if built >= 2024 and rng.random() < 0.6
                    else "Methanol dual-fuel" if built >= 2025 and rng.random() < 0.5
                    else "HSFO with scrubber" if rng.random() < 0.3 else "VLSFO")
            rows.append({
                "vessel_id": n,
                "imo_number": _imo(rng, used),
                "name": f"GL {VESSEL_WORDS[n - 1]}",
                "vessel_class": _vessel_class(size),
                "teu_capacity": size,
                "reefer_plugs": int(size * rng.uniform(0.08, 0.14)),
                "built_year": built,
                "flag": FLAGS[int(rng.integers(len(FLAGS)))],
                "fuel_type": fuel,
                "ownership": "chartered" if chartered else "owned",
                "daily_charter_cost_usd": (round(CHARTER_DAY_RATE[teu] * rng.uniform(0.85, 1.3), -2)
                                           if chartered else None),
                "in_fleet_from": start or date(2023, 1, 1) if built < 2024 else date(built, 3, 1),
                "in_fleet_to": end,
                "_service": service,
            })
    return pd.DataFrame(rows)


def build_rotations() -> pd.DataFrame:
    rows = []
    for s in ref.SERVICES:
        for direction, legs in (("headhaul", s.headhaul), ("backhaul", s.backhaul)):
            for seq, (port, days) in enumerate(legs, start=1):
                rows.append({"service_code": s.code, "direction": direction, "seq": seq,
                             "port_code": port, "days_from_previous": days})
    return pd.DataFrame(rows)


def _diverted(service: ref.Service, departure: date) -> bool:
    lo, hi = ref.RED_SEA_DIVERSION
    return service.suez and lo <= departure <= hi


def _active_fleet(vessels: pd.DataFrame, service: str, day: date) -> list[int]:
    v = vessels[vessels["_service"] == service]
    ok = v[(v["in_fleet_from"] <= day) & (v["in_fleet_to"].isna() | (v["in_fleet_to"] >= day))]
    ids = ok["vessel_id"].tolist()
    return ids or v["vessel_id"].tolist()


def _status(departure: date, arrival: date) -> str:
    today = ref.END + timedelta(days=14)
    if arrival < today:
        return "completed"
    return "in_progress" if departure <= today else "scheduled"


def build_voyages(vessels: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    rows, vid = [], 0
    for s_idx, s in enumerate(ref.SERVICES):
        first = ref.START + timedelta(days=s_idx % 7)
        week = 0
        while (dep := first + timedelta(days=7 * week)) <= ref.END + timedelta(days=42):
            fleet = _active_fleet(vessels, s.code, dep)
            vessel = fleet[week % len(fleet)]
            diverted = _diverted(s, dep)
            head_days = sum(d for _, d in s.headhaul) + (s.cape_extra_days if diverted else 0)
            back_dep = dep + timedelta(days=head_days + 3)
            iso = dep.isocalendar()
            for direction, d, letter in (("headhaul", dep, s.letters[0]),
                                         ("backhaul", back_dep, s.letters[1])):
                vid += 1
                legs = s.headhaul if direction == "headhaul" else s.backhaul
                span = sum(x for _, x in legs) + (s.cape_extra_days if diverted else 0)
                rows.append({
                    "voyage_id": vid,
                    "voyage_number": f"{s.code} {iso.year % 100:02d}{iso.week:02d}{letter}",
                    "service_code": s.code,
                    "vessel_id": vessel,
                    "direction": direction,
                    "routing": "cape_of_good_hope" if diverted else "standard",
                    "departure_date": d,
                    "status": _status(d, d + timedelta(days=span)),
                    "replanned": not (diverted and dep < date(2024, 2, 15)),
                })
            week += 1
    return pd.DataFrame(rows)


def _ts(day: date, hour: float) -> datetime:
    return datetime.combine(day, time(0), tzinfo=timezone.utc) + timedelta(hours=hour)


def _base_delay(rng: np.random.Generator, day: date, port: str) -> tuple[float, str]:
    """Hours of delay added at one port call, and the main cause."""
    calm = {2024: 1.0, 2025: 0.85}.get(day.year, 0.72)  # reliability improves after 2024
    hours = float(rng.gamma(1.3, 7.0)) * calm  # ordinary noise: most calls within a day
    cause = "Berth unavailability" if hours > 18 else ""
    if day.month in (12, 1, 2) and rng.random() < 0.15 * calm:
        extra = float(rng.gamma(2.0, 9.0))
        hours, cause = hours + extra, "Adverse weather"
    if rng.random() < 0.015 * calm:
        extra = float(rng.gamma(2.5, 14.0))
        hours, cause = hours + extra, "Mechanical failure"
    if rng.random() < 0.01:
        hours, cause = hours + float(rng.gamma(2.0, 10.0)), "Customs inspection hold"
    for c_port, lo, hi, mean in ref.CONGESTION:
        if port == c_port and lo <= day <= hi:
            hours, cause = hours + float(rng.gamma(3.0, mean / 3.0)), "Port congestion"
    lo, hi = ref.US_EAST_STRIKE
    if port in ref.US_EAST_PORTS and lo - timedelta(days=1) <= day <= hi + timedelta(days=6):
        hours, cause = hours + float(rng.uniform(48, 110)), "Labour strike"
    return hours, cause


def build_port_calls(voyages: pd.DataFrame, rng: np.random.Generator):
    services = {s.code: s for s in ref.SERVICES}
    calls, incidents = [], []
    pc_id = inc_id = 0
    for v in voyages.itertuples(index=False):
        s = services[v.service_code]
        legs = s.headhaul if v.direction == "headhaul" else s.backhaul
        longest = max(range(1, len(legs)), key=lambda i: legs[i][1])
        sched_h = act_h = stuck = 0.0  # stuck: unplanned Cape days that speed cannot recover
        for seq, (port, days) in enumerate(legs, start=1):
            extra = s.cape_extra_days * 24 if (v.routing != "standard" and seq - 1 == longest) else 0
            planned_extra = extra if v.replanned else 0
            sched_h += days * 24 + planned_extra
            act_h += days * 24 + extra
            stuck += extra - planned_extra
            # on each sea leg the ship speeds up and recovers part of any recoverable delay
            recoverable = act_h - sched_h - stuck
            if recoverable > 0:
                act_h -= recoverable * min(0.7, 0.08 * days)
            day = v.departure_date + timedelta(days=int(sched_h // 24))
            delay, cause = (0.0, "") if seq == 1 else _base_delay(rng, day, port)
            if v.routing != "standard":
                delay *= 1.5  # bunching and hub congestion while the network runs round Africa
            if seq > 1 and extra and not v.replanned:
                cause = "Red Sea diversion via Cape of Good Hope"
            act_h += delay
            stay = float(rng.uniform(16, 30))
            done = v.status != "scheduled" and day <= ref.END
            pc_id += 1
            calls.append({
                "port_call_id": pc_id, "voyage_id": v.voyage_id, "seq": seq, "port_code": port,
                "scheduled_arrival": _ts(v.departure_date, sched_h),
                "actual_arrival": _ts(v.departure_date, act_h) if done else None,
                "scheduled_departure": _ts(v.departure_date, sched_h + 22),
                "actual_departure": _ts(v.departure_date, act_h + stay) if done else None,
                "container_moves": None,
            })
            behind = act_h - sched_h
            if done and seq > 1 and cause and (delay > 18 or (extra and not v.replanned)):
                inc_id += 1
                hours = max(delay, behind if cause.startswith("Red Sea") else delay)
                incidents.append(_incident(inc_id, v, port, sched_h, hours, cause))
            sched_h += 22
            act_h += stay
    return pd.DataFrame(calls), pd.DataFrame(incidents)


def _severity(hours: float) -> str:
    if hours < 24:
        return "minor"
    if hours < 48:
        return "moderate"
    return "major" if hours < 120 else "critical"


def _incident(inc_id: int, v, port: str, sched_h: float, hours: float, cause: str) -> dict:
    started = _ts(v.departure_date, sched_h)
    return {
        "incident_id": inc_id,
        "incident_number": f"INC-{started.year}-{inc_id:05d}",
        "voyage_id": v.voyage_id,
        "port_code": port,
        "started_at": started,
        "delay_hours": round(hours, 1),
        "cause": cause,
        "severity": _severity(hours),
        "description": f"{cause} affected {v.voyage_number} at {port}; "
                       f"{round(hours)} hours behind schedule.",
    }


def build(rng: np.random.Generator) -> Network:
    vessels = build_vessels(rng)
    voyages = build_voyages(vessels, rng)
    calls, incidents = build_port_calls(voyages, rng)
    return Network(vessels, build_rotations(), voyages, calls, incidents)
