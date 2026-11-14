"""Container fleet (ISO 6346 numbers, owner code GLSU) and recent tracking events."""

from datetime import timedelta

import numpy as np
import pandas as pd

from grandline import reference as ref

LESSORS = ("Atlas Box Leasing", "Coldline Leasing", "Harbourline Equipment", "Meridian Container Finance")
ISO_LETTERS = {ch: v for ch, v in zip(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    (10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 34, 35,
     36, 37, 38), strict=True)}
TRACKING_DAYS = 90  # the warehouse keeps 90 days of tracking events (see data retention policy)
TRIP_DAYS = 55  # a container is busy for about this long per trip, including empty repositioning


def iso6346(serial: int) -> str:
    code = f"GLSU{serial:06d}"
    total = sum((ISO_LETTERS[c] if c.isalpha() else int(c)) * 2**i for i, c in enumerate(code))
    return f"{code}{total % 11 % 10}"


def assign_containers(bc: pd.DataFrame, rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Give every booking container a physical unit; units are reused trip after trip."""
    bc = bc.sort_values(["container_type", "_ready"], kind="stable").reset_index(drop=True)
    numbers = np.empty(len(bc), dtype=object)
    fleet_rows, serial = [], 100000
    days = (pd.to_datetime(bc["_ready"]).max() - pd.to_datetime(bc["_ready"]).min()).days or 1
    for ctype, idx in bc.groupby("container_type").indices.items():
        per_day = len(idx) / days
        size = max(20, int(per_day * TRIP_DAYS * 1.15))
        units = [iso6346(serial + k) for k in range(size)]
        serial += size
        numbers[idx] = [units[k % size] for k in range(len(idx))]
        reefer = ctype.endswith("RF")
        for u in units:
            leased = rng.random() < 0.42
            lessor = None
            if leased:
                lessor = "Coldline Leasing" if reefer and rng.random() < 0.35 else LESSORS[int(rng.integers(len(LESSORS)))]
            fleet_rows.append({
                "container_number": u, "container_type": ctype,
                "built_year": int(rng.integers(2010, 2026)),
                "ownership": "leased" if leased else "owned", "lessor": lessor,
                "status": rng.choice(["in_service", "in_service", "in_service", "in_service",
                                      "in_service", "in_service", "damaged", "off_hire"],
                                     p=[0.155] * 6 + [0.04, 0.03]),
            })
    bc["container_number"] = numbers
    return bc, pd.DataFrame(fleet_rows)


def tracking_events(bookings: pd.DataFrame, bc: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    today = pd.Timestamp(ref.END + timedelta(days=14), tz="UTC")
    since = today - pd.Timedelta(days=TRACKING_DAYS)
    b = bookings[bookings["status"] != "cancelled"].set_index("booking_id")
    recent = bc[pd.to_datetime(bc["_ready"]).dt.tz_localize("UTC") >= since - pd.Timedelta(days=40)]
    recent = recent[recent["booking_id"].isin(b.index)]
    info = b.loc[recent["booking_id"], ["origin_port", "destination_port", "voyage_id", "departure",
                                        "arrival"]].reset_index()
    n = len(recent)
    ready = pd.to_datetime(recent["_ready"].to_numpy()).tz_localize("UTC") + pd.to_timedelta(
        rng.uniform(8, 18, n), unit="h")
    dep = pd.to_datetime(info["departure"], utc=True).to_numpy()
    arr = pd.to_datetime(info["arrival"], utc=True)
    steps = [
        ("GATE_OUT_EMPTY", ready - pd.to_timedelta(rng.uniform(1, 4, n), unit="D"), "origin_port", False),
        ("GATE_IN_FULL", ready, "origin_port", False),
        ("LOADED", pd.DatetimeIndex(dep) - pd.to_timedelta(rng.uniform(3, 12, n), unit="h"), "origin_port", True),
        ("DISCHARGED", arr + pd.to_timedelta(rng.uniform(4, 20, n), unit="h"), "destination_port", True),
        ("GATE_OUT_FULL", arr + pd.to_timedelta(rng.uniform(1, 5, n), unit="D"), "destination_port", False),
        ("EMPTY_RETURN", arr + pd.to_timedelta(rng.uniform(5, 14, n), unit="D"), "destination_port", False),
    ]
    frames = []
    for etype, when, port_col, with_voyage in steps:
        when = pd.Series(pd.DatetimeIndex(when))
        frames.append(pd.DataFrame({
            "container_number": recent["container_number"].to_numpy(),
            "booking_id": recent["booking_id"].to_numpy(),
            "event_type": etype, "event_time": when.to_numpy(),
            "port_code": info[port_col].to_numpy(),
            "voyage_id": info["voyage_id"].to_numpy() if with_voyage else None,
        }))
    ev = pd.concat(frames, ignore_index=True)
    ev = ev[ev["event_time"].notna()]
    t = pd.to_datetime(ev["event_time"], utc=True)
    ev = ev[(t >= since) & (t <= today)].sort_values("event_time", kind="stable")
    ev.insert(0, "event_id", np.arange(1, len(ev) + 1))
    ev["voyage_id"] = ev["voyage_id"].astype("Int64")
    return ev
