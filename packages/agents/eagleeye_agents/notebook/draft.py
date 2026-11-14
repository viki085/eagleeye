"""Notebook drafts from the model: parsing and the static checks on every cell."""

import json
from dataclasses import dataclass, replace

from eagleeye_sandbox.checks_python import check_python
from eagleeye_sandbox.types import MAX_NOTEBOOK_CELLS, CodeRejected

MAX_PURPOSE_CHARS = 160


@dataclass(frozen=True)
class CellDraft:
    purpose: str
    code: str


@dataclass(frozen=True)
class NotebookDraft:
    title: str
    cells: tuple[CellDraft, ...]

    def with_cell(self, index: int, code: str) -> "NotebookDraft":
        cells = list(self.cells)
        cells[index] = replace(cells[index], code=code)
        return replace(self, cells=tuple(cells))


def parse_notebook(raw: str) -> NotebookDraft:
    """The model's JSON → a draft (at most MAX_NOTEBOOK_CELLS non-empty cells)."""
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("cells"), list):
        raise ValueError("expected {title, cells: [...]}")
    cells = tuple(
        CellDraft(
            str(c.get("purpose") or f"Step {i + 1}").strip()[:MAX_PURPOSE_CHARS],
            str(c.get("code") or "").strip(),
        )
        for i, c in enumerate(data["cells"])
        if isinstance(c, dict) and str(c.get("code") or "").strip()
    )[:MAX_NOTEBOOK_CELLS]
    if not cells:
        raise ValueError("the notebook has no cells")
    return NotebookDraft(str(data.get("title") or "Exploratory analysis").strip()[:80], cells)


def parse_repair(raw: str) -> str:
    data = json.loads(raw)
    code = str(data.get("code") or "").strip() if isinstance(data, dict) else ""
    if not code:
        raise ValueError("no code")
    return code


def first_rejected(draft: NotebookDraft) -> tuple[int, str] | None:
    """(cell index, reason) for the first cell the static checks reject, or None."""
    for i, cell in enumerate(draft.cells):
        try:
            check_python(cell.code)
        except CodeRejected as exc:
            return i, f"The check rejected the code ({exc.code}): {exc.user_message}"
    return None
