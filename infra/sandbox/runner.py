"""Runs ONE analysis task inside the sandbox container and writes /work/out/result.json.

Input  /work/in/task.json
       {mode: "sql"|"python", code, inputs: [{name, file}], max_rows, max_tables}
Output /work/out/result.json {status, error, error_type, stats, tables: [...], stdout}
       /work/out/<file>.parquet  one per result table

This file is trusted code baked into the image; `code` is untrusted. Isolation comes from
the container (no network, read-only root, caps, non-root), not from anything in here.
"""

import contextlib
import io
import json
import math
import re
import sys
import traceback
from pathlib import Path

IN_DIR = Path("/work/in")
OUT_DIR = Path("/work/out")
SAFE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
MAX_STDOUT_CHARS = 4000
MAX_ERROR_CHARS = 800
MAX_STATS = 60


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


def run_python(task: dict) -> dict:
    import numpy as np
    import pandas as pd
    import pyarrow as pa

    datasets = {i["name"]: pd.read_parquet(IN_DIR / i["file"]) for i in task["inputs"]}
    tables: dict[str, pd.DataFrame] = {}
    stats: dict[str, object] = {}

    def save_table(name: str, df: pd.DataFrame) -> None:
        if not SAFE_NAME.match(name):
            raise ValueError("table name must be lower_snake_case")
        if not isinstance(df, pd.DataFrame):
            raise TypeError("save_table expects a pandas DataFrame")
        if name not in tables and len(tables) >= task["max_tables"]:
            raise ValueError(f"at most {task['max_tables']} result tables")
        tables[name] = df

    def save_stat(key: str, value: object) -> None:
        if len(stats) >= MAX_STATS and key not in stats:
            raise ValueError(f"at most {MAX_STATS} stats")
        stats[str(key)] = _json_safe(value)

    namespace = {
        "datasets": datasets,
        "save_table": save_table,
        "save_stat": save_stat,
        "pd": pd,
        "np": np,
        "__name__": "__analysis__",
    }
    exec(compile(task["code"], "<analysis>", "exec"), namespace)  # noqa: S102 — the sandbox's job
    written = []
    for name, df in tables.items():
        frame = df.reset_index() if df.index.name or df.index.nlevels > 1 else df
        frame.columns = [str(c) for c in frame.columns]
        table = pa.Table.from_pandas(frame, preserve_index=False)
        written.append(_write_table(name, table, task["max_rows"]))
    return {"tables": written, "stats": stats}


def main() -> int:
    stdout = io.StringIO()
    try:
        task = json.loads((IN_DIR / "task.json").read_text(encoding="utf-8"))
        for item in task["inputs"]:
            if not SAFE_NAME.match(item["name"]) or "/" in item["file"] or "\\" in item["file"]:
                raise ValueError("invalid input name")
        with contextlib.redirect_stdout(stdout):
            body = run_sql(task) if task["mode"] == "sql" else run_python(task)
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
