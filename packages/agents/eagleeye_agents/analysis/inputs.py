"""Inputs for one analysis: resolve ids (owner-checked), name them ds_1…, describe them.

The description the model gets is schema + profile digest + a masked 5-row sample; raw
rows never go to the model beyond that.
"""

import io
from typing import Any

import pyarrow.parquet as pq
from eagleeye_core.pii import MASK, looks_personal
from eagleeye_datasets.render import profile_digest, schema_line
from eagleeye_datasets.values import clip, jsonable
from eagleeye_sandbox.types import SandboxInput

from eagleeye_agents.analysis.types import LoadedInput

MAX_INPUTS = 6
SAMPLE_ROWS = 5


def sample_rows(item: LoadedInput, n: int = SAMPLE_ROWS) -> list[list[Any]]:
    table = pq.read_table(io.BytesIO(item.parquet)).slice(0, n)
    names = table.column_names
    hidden = [name.lower() in item.pii_columns for name in names]
    return [
        [
            None
            if r[c] is None
            else MASK
            if hidden[i] or looks_personal(r[c])
            else clip(jsonable(r[c]), 40)
            for i, c in enumerate(names)
        ]
        for r in table.to_pylist()
    ]


def describe(name: str, item: LoadedInput) -> str:
    kind = "uploaded data file" if item.kind == "dataset" else "earlier result table"
    lines = [
        f"TABLE {name} — {kind} '{item.title}' (id {item.ref_id}), {item.row_count:,} rows",
        f"  columns: {schema_line(item.columns)}",
    ]
    if item.profile:
        digest = profile_digest(item.title, item.profile).splitlines()[1:]
        lines += [f"  {line}" for line in digest]
    rows = sample_rows(item)
    if rows:
        lines.append("  sample rows (*** = personal data, hidden from you):")
        lines.append("  " + " | ".join(c["name"] for c in item.columns))
        lines += ["  " + " | ".join("" if v is None else str(v) for v in r) for r in rows]
    return "\n".join(lines)


def sandbox_inputs(named: list[tuple[str, LoadedInput]]) -> tuple[SandboxInput, ...]:
    return tuple(SandboxInput(name, item.parquet, item.columns) for name, item in named)


def pii_for_results(named: list[tuple[str, LoadedInput]]) -> set[str]:
    """Column names hidden in result previews: any PII column of any input."""
    return {c for _, item in named for c in item.pii_columns}
