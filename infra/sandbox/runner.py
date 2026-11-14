"""Runs ONE analysis task inside the sandbox container and writes /work/out/result.json.

Input  /work/in/task.json
       {mode: "sql"|"python"|"notebook", code, cells, inputs: [{name, file}], max_rows,
        max_tables, max_figures, max_figure_bytes}
Output /work/out/result.json {status, error, error_type, stats, tables: [...], stdout,
       cells: [...], figures: [...], failed_cell}
       /work/out/<file>.parquet one per result table; /work/out/<fig>.png one per figure

Notebook mode runs the cells in order in ONE namespace (like a notebook kernel), records each
cell's stdout, tables, stats and figures, and stops at the first failing cell; the earlier
cells' outputs are still returned so that one cell can be repaired.

This file is trusted code baked into the image; `code` and `cells` are untrusted. Isolation
comes from the container (no network, read-only root, caps, non-root), not from anything here.
"""

import contextlib
import io
import json
import math
import os
import re
import shutil
import sys
import traceback
from pathlib import Path

# Docker mounts /work/in and /work/out; the Lambda handler points these at /tmp
IN_DIR = Path(os.environ.get("SANDBOX_IN_DIR", "/work/in"))
OUT_DIR = Path(os.environ.get("SANDBOX_OUT_DIR", "/work/out"))
SAFE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
MAX_STDOUT_CHARS = 4000
MAX_ERROR_CHARS = 800
MAX_STATS = 60
MPL_CACHE_BAKED = Path("/opt/mplconfig")  # font cache built into the image
MPL_CACHE_RUN = Path("/tmp/matplotlib")  # noqa: S108 - the sandbox's writable temp folder
FIGURE_DPI = (100, 60)  # a second, smaller try when a figure is over the size cap


def _json_safe(value):  # noqa: ANN001, ANN202 — untyped on purpose: numpy/pandas scalars
    """numpy/pandas scalars → plain JSON values; NaN/inf → None."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in list(value.items())[:MAX_STATS]}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in list(value)[:200]]
    if hasattr(value, "item") and not hasattr(value, "__len__"):
        value = value.item()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, int):
        return value
    if hasattr(value, "tolist"):
        return _json_safe(value.tolist())
    return str(value)


def _write_table(name: str, table, max_rows: int) -> dict:  # noqa: ANN001
    import pyarrow.parquet as pq

    truncated = table.num_rows > max_rows
    if truncated:
        table = table.slice(0, max_rows)
    file = f"{name}.parquet"
    pq.write_table(table, OUT_DIR / file, compression="zstd")
    columns = [{"name": f.name, "type": str(f.type)} for f in table.schema]
    return {
        "name": name,
        "file": file,
        "rows": table.num_rows,
        "columns": columns,
        "truncated": truncated,
    }


def run_sql(task: dict) -> dict:
    import duckdb

    con = duckdb.connect(":memory:")
    con.execute("SET threads=1")
    con.execute("SET temp_directory='/tmp/duckdb'")
    for item in task["inputs"]:
        # names are validated in main(); the path is a bound parameter
        con.execute(
            f'CREATE TABLE "{item["name"]}" AS SELECT * FROM read_parquet(?)',  # noqa: S608
            [str(IN_DIR / item["file"])],
        )
    con.execute("SET enable_external_access=false")
    con.execute("SET lock_configuration=true")
    result = con.execute(task["code"]).to_arrow_table()  # DuckDB 2.x name
    return {"tables": [_write_table("result", result, task["max_rows"])], "stats": {}}


class _PythonEnv:
    """The namespace analysis code runs in, and what it saved."""

    def __init__(self, task: dict) -> None:
        import numpy as np
        import pandas as pd

        self.task = task
        self.tables: dict[str, object] = {}
        self.stats: dict[str, object] = {}
        datasets = {i["name"]: pd.read_parquet(IN_DIR / i["file"]) for i in task["inputs"]}
        self.namespace = {
            "datasets": datasets,
            "save_table": self.save_table,
            "save_stat": self.save_stat,
            "pd": pd,
            "np": np,
            "__name__": "__analysis__",
        }

    def save_table(self, name: str, df) -> None:  # noqa: ANN001
        import pandas as pd

        if not SAFE_NAME.match(name):
            raise ValueError("table name must be lower_snake_case")
        if not isinstance(df, pd.DataFrame):
            raise TypeError("save_table expects a pandas DataFrame")
        if name not in self.tables and len(self.tables) >= self.task["max_tables"]:
            raise ValueError(f"at most {self.task['max_tables']} result tables")
        self.tables[name] = df

    def save_stat(self, key: str, value: object) -> None:
        if len(self.stats) >= MAX_STATS and key not in self.stats:
            raise ValueError(f"at most {MAX_STATS} stats")
        self.stats[str(key)] = _json_safe(value)

    def run(self, code: str, label: str) -> None:
        exec(compile(code, label, "exec"), self.namespace)  # noqa: S102 — the sandbox's job

    def written_tables(self) -> list[dict]:
        import pyarrow as pa

        written = []
        for name, df in self.tables.items():
            frame = df.reset_index() if df.index.name or df.index.nlevels > 1 else df
            frame.columns = [str(c) for c in frame.columns]
            table = pa.Table.from_pandas(frame, preserve_index=False)
            written.append(_write_table(name, table, self.task["max_rows"]))
        return written


def run_python(task: dict) -> dict:
    env = _PythonEnv(task)
    env.run(task["code"], "<analysis>")
    return {"tables": env.written_tables(), "stats": env.stats}


def _prepare_matplotlib():  # noqa: ANN202
    """Agg backend (no display) and the font cache copied from the image (fast import)."""
    if MPL_CACHE_BAKED.is_dir() and not MPL_CACHE_RUN.exists():
        shutil.copytree(MPL_CACHE_BAKED, MPL_CACHE_RUN)
    os.environ["MPLCONFIGDIR"] = str(MPL_CACHE_RUN)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _png(fig, max_bytes: int) -> bytes | None:  # noqa: ANN001
    for dpi in FIGURE_DPI:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
        if buf.tell() <= max_bytes:
            return buf.getvalue()
    return None


def _collect_figures(plt, cell: int, figures: list, task: dict) -> tuple[list[str], str]:  # noqa: ANN001
    """Saves and closes every open figure; returns (names, note)."""
    names: list[str] = []
    notes: list[str] = []
    for number in plt.get_fignums():
        if len(figures) >= task["max_figures"]:
            notes.append(f"figure limit ({task['max_figures']}) reached; later figures dropped")
            break
        png = _png(plt.figure(number), task["max_figure_bytes"])
        if png is None:
            notes.append("a figure was too large to keep")
            continue
        name = f"fig_{cell}_{len(names) + 1}"
        (OUT_DIR / f"{name}.png").write_bytes(png)
        figures.append({"name": name, "file": f"{name}.png", "cell": cell})
        names.append(name)
    plt.close("all")
    return names, "; ".join(dict.fromkeys(notes))


def _run_cell(env: _PythonEnv, code: str, index: int) -> tuple[str, str, str]:
    """(stdout, error line, error type) for one cell."""
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            env.run(code, f"<cell {index}>")
    except Exception as exc:  # noqa: BLE001 — becomes the cell's error
        line = traceback.format_exception_only(type(exc), exc)[-1].strip()
        return out.getvalue(), line, type(exc).__name__
    return out.getvalue(), "", ""


def _display(*objects: object) -> None:
    """Jupyter's display() for notebook code: tables print compactly, everything else as text."""
    for obj in objects:
        to_string = getattr(obj, "to_string", None)
        if callable(to_string) and hasattr(obj, "shape"):
            print(to_string(max_rows=20, max_cols=12))
        else:
            print(obj)


def run_notebook(task: dict) -> dict:
    plt = _prepare_matplotlib()
    env = _PythonEnv(task)
    # the usual notebook names are pre-loaded, as in a data scientist's Jupyter session
    import seaborn as sns

    env.namespace.update({"plt": plt, "sns": sns, "display": _display})
    cells: list[dict] = []
    figures: list[dict] = []
    body: dict = {}
    for index, code in enumerate(task["cells"]):
        tables_before, stats_before = set(env.tables), dict(env.stats)
        stdout, error, error_type = _run_cell(env, code, index)
        names, note = _collect_figures(plt, index, figures, task)
        cells.append(
            {
                "index": index,
                "stdout": stdout[:MAX_STDOUT_CHARS],
                "tables": [n for n in env.tables if n not in tables_before],
                "stats": {k: v for k, v in env.stats.items() if stats_before.get(k) != v},
                "figures": names,
                "error": error[:MAX_ERROR_CHARS],
                "note": note,
            }
        )
        if error:
            body = {
                "status": "error",
                "error": f"Cell {index}: {error}"[:MAX_ERROR_CHARS],
                "error_type": error_type,
                "failed_cell": index,
            }
            break
    return {
        "tables": env.written_tables(),
        "stats": env.stats,
        "cells": cells,
        "figures": figures,
        "failed_cell": None,
        **body,
    }


RUNNERS = {"sql": run_sql, "python": run_python, "notebook": run_notebook}


def main() -> int:
    stdout = io.StringIO()
    try:
        task = json.loads((IN_DIR / "task.json").read_text(encoding="utf-8"))
        for item in task["inputs"]:
            if not SAFE_NAME.match(item["name"]) or "/" in item["file"] or "\\" in item["file"]:
                raise ValueError("invalid input name")
        with contextlib.redirect_stdout(stdout):
            body = RUNNERS[task["mode"]](task)
        result = {"status": "ok", "error": "", "error_type": "", **body}
    except BaseException as exc:  # noqa: BLE001 — every failure must become a structured result
        last = traceback.format_exception_only(type(exc), exc)[-1].strip()
        result = {
            "status": "error",
            "error": last[:MAX_ERROR_CHARS],
            "error_type": type(exc).__name__,
            "tables": [],
            "stats": {},
        }
    result["stdout"] = stdout.getvalue()[:MAX_STDOUT_CHARS]
    (OUT_DIR / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
