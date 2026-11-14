"""[file name] references in a question: the user's way of pointing at their own files.

The web app inserts "[brent_crude_daily.csv]" when a file is dragged into the message box. Here
the token is matched (case-insensitively) to the user's data files and visible documents by
file name or title. Resolved references send the run to the planner, which is told exactly which
files were meant (with ids, so it doesn't have to guess). Unmatched tokens are left as plain text;
numeric tokens such as citation markers "[1]" are ignored.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

TOKEN = re.compile(r"\[([^\[\]\n]{2,200})\]")
_NUMERIC = re.compile(r"^\s*\d+(\s*,\s*\d+)*\s*$")
MAX_COLUMNS_SHOWN = 20


@dataclass(frozen=True)
class FileRef:
    kind: str  # "data_file" | "document"
    id: str
    name: str
    columns: tuple[str, ...] = ()
    scope: str = ""


def tokens(question: str) -> list[str]:
    out: list[str] = []
    for match in TOKEN.findall(question):
        name = match.strip().strip("'\"")
        if name and not _NUMERIC.match(name) and name.lower() not in (t.lower() for t in out):
            out.append(name)
    return out


def dataset_names(d: Any) -> set[str]:
    names = {d.title, d.filename}
    if getattr(d, "sheet", ""):
        names.add(f"{d.filename} ({d.sheet})")
    return {n.lower() for n in names if n}


def resolve_datasets(names: Sequence[str], datasets: Sequence[Any]) -> list[FileRef]:
    keys = {n.lower() for n in names}
    return [
        FileRef("data_file", d.id, d.title, tuple(c["name"] for c in d.columns))
        for d in datasets
        if keys & dataset_names(d)
    ]


def dedupe(refs: Sequence[FileRef]) -> list[FileRef]:
    seen: set[str] = set()
    return [r for r in refs if not (r.id in seen or seen.add(r.id))]


def planner_note(refs: Sequence[FileRef]) -> str:
    """Appended to the planner's system prompt when the question names files."""
    if not refs:
        return ""
    lines = ["The user pointed at these files with [brackets] in the question. Use them:"]
    for r in refs:
        if r.kind == "data_file":
            cols = ", ".join(r.columns[:MAX_COLUMNS_SHOWN])
            more = " …" if len(r.columns) > MAX_COLUMNS_SHOWN else ""
            lines.append(
                f"- data file '{r.name}', id {r.id} (columns: {cols}{more}): pass this id "
                "to analyze_data or get_dataset_profile"
            )
        else:
            lines.append(
                f"- {r.scope} document '{r.name}', id {r.id}: search it with "
                "search_knowledge (include its title in the query)"
            )
    return "\n".join(lines)
