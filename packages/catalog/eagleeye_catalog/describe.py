"""Draft missing descriptions with the fast model (C5 §2: LLM-drafted, admin-reviewed)."""

import json
import logging
from dataclasses import replace

from eagleeye_llm.gateway import ChatMessage, LLMGateway

from eagleeye_catalog.models import TableInfo

logger = logging.getLogger(__name__)

PROMPT = """You document database tables for business users.
Given a table and its columns, return ONLY JSON:
{"table": "<one sentence: what one row represents>", "columns": {"<column>": "<short meaning>"}}
Describe only what the names, types and keys make clear; do not invent business rules."""


def needs_description(t: TableInfo) -> bool:
    return not t.description or any(not c.description for c in t.columns)


async def draft_description(llm: LLMGateway, t: TableInfo) -> TableInfo:
    listing = "\n".join(
        f"- {c.name} {c.data_type}"
        + (" PK" if c.is_pk else "")
        + (f" -> {c.fk_ref}" if c.fk_ref else "")
        for c in t.columns
    )
    try:
        raw, _ = await llm.complete(
            "fast",
            [ChatMessage("system", PROMPT), ChatMessage("user", f"Table {t.key}\n{listing}")],
            max_tokens=500,
            json_mode=True,
        )
        data = json.loads(raw)
    except Exception:
        logger.warning("could not draft description for %s", t.key, exc_info=True)
        return t
    drafted = data.get("columns") if isinstance(data.get("columns"), dict) else {}
    columns = tuple(
        replace(c, description=c.description or str(drafted.get(c.name, ""))[:300])
        for c in t.columns
    )
    table_desc = t.description or str(data.get("table", ""))[:300]
    return replace(t, description=table_desc, columns=columns)
