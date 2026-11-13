"""Column headers → safe SQL identifiers, keeping a map back to the original header."""

import re
from collections.abc import Sequence
from typing import Any

MAX_NAME_CHARS = 60
_NON_WORD = re.compile(r"[^a-z0-9]+")
# Unquoted, these break model-written SQL; a suffix is cheaper than teaching quoting.
_RESERVED = frozenset(
    "all and any as asc between by case cast column create default desc distinct else end "
    "except false from full group having in inner intersect into is join left like limit "
    "not null offset on or order outer primary right select table then to true union unique "
    "using values when where window with".split()
)


def _base(header: Any, position: int) -> str:
    text = "" if header is None else str(header).strip().lower()
    name = _NON_WORD.sub("_", text).strip("_")[:MAX_NAME_CHARS]
    if not name:
        return f"column_{position + 1}"
    if name[0].isdigit():
        name = f"c_{name}"
    return f"{name}_col" if name in _RESERVED else name


def safe_names(headers: Sequence[Any]) -> tuple[list[str], dict[str, str]]:
    """`["Order ID", "Order ID", "2024"]` → `["order_id", "order_id_2", "c_2024"]` + the map."""
    names: list[str] = []
    seen: dict[str, int] = {}
    for i, header in enumerate(headers):
        base = _base(header, i)
        count = seen.get(base, 0) + 1
        seen[base] = count
        name = base if count == 1 else f"{base}_{count}"
        while name in names:  # e.g. "a_2" already taken by a real header
            count += 1
            name = f"{base}_{count}"
        names.append(name)
    originals = ["" if h is None else str(h).strip() for h in headers]
    return names, {n: o or n for n, o in zip(names, originals, strict=True)}


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
