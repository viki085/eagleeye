import datetime as dt
import uuid
from decimal import Decimal
from typing import Any


def jsonable(value: Any) -> Any:
    """Parquet/DB values → JSON-safe values for API responses."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes | bytearray):
        return "<binary>"
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return str(value)
