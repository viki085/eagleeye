"""JSON-safe values for profiles, previews and API responses."""

import math
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

MAX_CELL_CHARS = 120


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    return str(value)


def clip(value: Any, limit: int = MAX_CELL_CHARS) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[: limit - 1] + "…"
    return value


def round_sig(value: Any, digits: int = 6) -> Any:
    """Floats rounded to `digits` significant figures; everything else unchanged."""
    if not isinstance(value, float) or value == 0 or not math.isfinite(value):
        return value
    return round(value, digits - 1 - math.floor(math.log10(abs(value))))
