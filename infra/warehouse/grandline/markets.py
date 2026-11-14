"""Market curves: spot freight rates per lane (USD per 40ft, headhaul) and fuel prices.

Freight curves are invented but follow the real shape of 2024-2026 (Red Sea spike in 2024,
normalisation in 2025, overcapacity in 2026). Fuel follows the real daily Brent price.
"""

from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

BRENT_CSV = Path(__file__).resolve().parents[3] / "data" / "public" / "brent_daily_fred.csv"

# (year, month) -> USD per 40ft container on the headhaul leg
SPOT_ANCHORS: dict[str, tuple[tuple[int, int, float], ...]] = {
    "AEU": ((2024, 1, 4500), (2024, 2, 4000), (2024, 4, 2900), (2024, 7, 7600), (2024, 9, 5600),
            (2024, 12, 4900), (2025, 2, 3300), (2025, 5, 2600), (2025, 8, 3200), (2025, 11, 2200),
            (2026, 2, 2400), (2026, 5, 1900), (2026, 8, 2300), (2026, 10, 1800)),
    "AMD": ((2024, 1, 5000), (2024, 2, 4600), (2024, 4, 3300), (2024, 7, 7900), (2024, 9, 6000),
            (2024, 12, 5200), (2025, 2, 3700), (2025, 5, 2900), (2025, 8, 3500), (2025, 11, 2500),
            (2026, 2, 2700), (2026, 5, 2200), (2026, 8, 2500), (2026, 10, 2000)),
    "TPW": ((2024, 1, 2500), (2024, 3, 2800), (2024, 6, 6000), (2024, 9, 5000), (2024, 12, 4000),
            (2025, 3, 2600), (2025, 6, 3900), (2025, 9, 2200), (2026, 1, 2300), (2026, 6, 2100),
            (2026, 10, 1900)),
    "AUE": ((2024, 1, 3700), (2024, 3, 3900), (2024, 6, 7800), (2024, 9, 6600), (2024, 12, 5400),
            (2025, 3, 3700), (2025, 6, 5200), (2025, 9, 3200), (2026, 1, 3300), (2026, 6, 3000),
            (2026, 10, 2700)),
    "ECS": ((2024, 1, 3500), (2024, 6, 8500), (2024, 10, 6000), (2025, 3, 4500), (2025, 9, 3000),
            (2026, 6, 2800), (2026, 10, 2600)),
    "TAT": ((2024, 1, 2400), (2024, 7, 2600), (2025, 1, 2300), (2025, 7, 2200), (2026, 1, 2100),
            (2026, 10, 1950)),
    "AMI": ((2024, 1, 1500), (2024, 6, 3000), (2024, 10, 2200), (2025, 4, 1600), (2026, 1, 1500),
            (2026, 10, 1350)),
    "IAS": ((2024, 1, 700), (2024, 6, 950), (2025, 1, 800), (2025, 7, 750), (2026, 1, 700),
            (2026, 10, 650)),
}
BACKHAUL_RATIO = {"AEU": 0.3, "AMD": 0.35, "TPW": 0.25, "AUE": 0.3, "ECS": 0.4, "TAT": 0.55,
                  "AMI": 0.45, "IAS": 0.8}
SIZE_FACTOR = {"20DV": 0.62, "40DV": 0.95, "40HC": 1.0, "20RF": 1.25, "40RF": 1.8,
               "20TK": 1.4, "40OT": 1.35}


@lru_cache
def _curve(lane: str) -> pd.Series:
    pts = SPOT_ANCHORS[lane]
    idx = pd.to_datetime([date(y, m, 15) for y, m, _ in pts])
    s = pd.Series([v for *_, v in pts], index=idx)
    days = pd.date_range("2023-06-01", "2027-03-31", freq="D")
    return s.reindex(s.index.union(days)).interpolate("time").ffill().bfill().reindex(days)


def spot_rate(lane: str, day: date, headhaul: bool, container_type: str) -> float:
    base = float(_curve(lane).loc[pd.Timestamp(day)])
    if not headhaul:
        base *= BACKHAUL_RATIO[lane]
    return base * SIZE_FACTOR[container_type]


def spot_rates(lane: str, days: np.ndarray) -> np.ndarray:
    """Vectorised headhaul 40ft spot rate for an array of numpy datetime64[D]."""
    return _curve(lane).reindex(pd.to_datetime(days)).to_numpy()


@lru_cache
def brent() -> pd.Series:
    df = pd.read_csv(BRENT_CSV, na_values=".")
    s = pd.Series(df.iloc[:, 1].astype(float).to_numpy(),
                  index=pd.to_datetime(df.iloc[:, 0]))
    days = pd.date_range("2023-06-01", "2027-03-31", freq="D")
    return s.reindex(s.index.union(days)).interpolate("time").ffill().bfill().reindex(days)


def vlsfo_price(days) -> np.ndarray:
    """Very-low-sulphur fuel oil, USD per tonne, tracking Brent (USD per barrel)."""
    return brent().reindex(pd.to_datetime(days)).to_numpy() * 7.1 + 45.0
