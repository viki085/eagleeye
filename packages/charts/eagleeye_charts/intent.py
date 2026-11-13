"""What the model may ask for. It names columns and a chart type; it never supplies data,
colours, expressions or raw spec fragments (C6 §5)."""

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

ChartType = Literal["bar", "line", "area", "scatter", "histogram"]
Aggregate = Literal["sum", "mean", "median", "count", "min", "max"]
Sort = Literal["x", "-x", "y", "-y"]

MAX_POINTS = 2000
MAX_SERIES = 8
MAX_MEASURES = 4
DEFAULT_TOP_N = 20
HISTOGRAM_BINS = 20


class ChartIntent(BaseModel):
    type: ChartType = Field(
        description="bar: compare categories; line/area: change over an ordered x (time or "
        "number); scatter: relation between two numeric columns; histogram: distribution of "
        "one numeric column."
    )
    x: str = Field(max_length=100, description="Column for the x axis (histogram: the column).")
    y: str | list[str] | None = Field(
        default=None,
        description="Numeric column for the y axis, or up to 4 numeric columns in the same unit to "
        "compare side by side (e.g. ['revenue', 'target']). Omit to count rows.",
    )
    color: str | None = Field(
        default=None, max_length=100, description="Optional category column: one series per value."
    )
    aggregate: Aggregate | None = Field(
        default=None, description="How to combine y per x. Default: sum (count when y is omitted)."
    )
    sort: Sort | None = Field(
        default=None, description="bar only: order by x or by y; '-' = descending."
    )
    top_n: int | None = Field(
        default=None, ge=1, le=50, description="bar only: keep the top N categories."
    )
    title: str = Field(min_length=3, max_length=120, description="Short chart title.")


class ChartError(Exception):
    """The intent can't be drawn from this data. `user_message` goes back to the model."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


@dataclass(frozen=True)
class Chart:
    spec: dict[str, Any]  # Vega-Lite, data inline, no colours, no expressions
    summary: str  # computed by code; what the model may quote
    values: tuple[float, ...] = field(default_factory=tuple)  # plotted numbers (evidence)
    notes: tuple[str, ...] = field(default_factory=tuple)
