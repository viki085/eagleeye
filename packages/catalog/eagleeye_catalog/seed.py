"""Curated YAML seed → merged onto introspected tables (meaning on top of structure)."""

import logging
from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from eagleeye_catalog.models import ColumnInfo, Example, Grant, Metric, TableInfo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeedSpec:
    source: dict[str, Any]
    grants: tuple[Grant, ...]
    tables: dict[str, dict[str, Any]]
    metrics: tuple[Metric, ...]
    examples: tuple[Example, ...]


def load_seed(name_or_path: str) -> SeedSpec:
    path = Path(name_or_path)
    if path.suffix in (".yaml", ".yml") and path.exists():
        text = path.read_text("utf-8")
    else:
        text = (
            resources.files("eagleeye_catalog.seeds")
            .joinpath(f"{name_or_path}.yaml")
            .read_text("utf-8")
        )
    raw = yaml.safe_load(text)
    grants = tuple(
        Grant(
            role=role,
            allowed_tables=tuple(g["tables"]) if g.get("tables") else None,
            can_see_pii=bool(g.get("pii", False)),
        )
        for role, g in (raw.get("grants") or {}).items()
    )
    return SeedSpec(
        source=raw["source"],
        grants=grants,
        tables=raw.get("tables") or {},
        metrics=tuple(Metric(**m) for m in raw.get("metrics") or []),
        examples=tuple(Example(**e) for e in raw.get("examples") or []),
    )


def _column_spec(spec: Any) -> tuple[str, bool | None]:
    if isinstance(spec, dict):
        return str(spec.get("description", "")), spec.get("pii")
    return str(spec or ""), None


def _merge_columns(columns: tuple[ColumnInfo, ...], spec: dict[str, Any]) -> tuple[ColumnInfo, ...]:
    merged = []
    for c in columns:
        description, pii = _column_spec(spec.get(c.name))
        merged.append(
            replace(c, description=description or c.description, pii=c.pii if pii is None else pii)
        )
    return tuple(merged)


def merge(introspected: list[TableInfo], seed: SeedSpec) -> list[TableInfo]:
    """Seeded tables take description/enabled/sensitivity/PII from the seed; unseeded tables
    are imported disabled until a data admin reviews them (C5 §2)."""
    out: list[TableInfo] = []
    for t in introspected:
        spec = seed.tables.get(t.key)
        if spec is None:
            logger.info("new table %s imported disabled (not in seed)", t.key)
            out.append(replace(t, enabled=False))
            continue
        out.append(
            replace(
                t,
                description=spec.get("description", t.description),
                enabled=bool(spec.get("enabled", False)),
                sensitivity=spec.get("sensitivity", t.sensitivity),
                columns=_merge_columns(t.columns, spec.get("columns") or {}),
            )
        )
    missing = set(seed.tables) - {t.key for t in introspected}
    for key in sorted(missing):
        logger.info("seeded table %s not visible to the source account; skipped", key)
    return out
