"""Escape corpus against the real sandbox image (C6 §8). Skipped when Docker or the image
is missing. These run code that skips the static checks on purpose: the container alone
must contain it."""

import asyncio
import io

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from eagleeye_sandbox.docker_executor import DockerExecutor
from eagleeye_sandbox.types import SandboxInput, SandboxTask

pytestmark = pytest.mark.integration
IMAGE = "eagleeye-sandbox:1"
EXECUTOR = DockerExecutor(IMAGE, mem_mb=256, timeout_s=20)

if not asyncio.run(EXECUTOR.available()):
    pytest.skip("sandbox image not available", allow_module_level=True)


def parquet() -> bytes:
    buf = io.BytesIO()
    pq.write_table(pa.table({"g": ["a", "a", "b"], "v": [1.0, 2.0, 5.0]}), buf)
    return buf.getvalue()


INPUT = (SandboxInput("ds_1", parquet(), ({"name": "g", "type": "VARCHAR"},)),)


async def run(code: str, mode: str = "python") -> object:
    return await EXECUTOR.run(SandboxTask(mode, code, INPUT))  # type: ignore[arg-type]


async def test_sql_mode_returns_a_table() -> None:
    result = await run("SELECT g, SUM(v) AS total FROM ds_1 GROUP BY g ORDER BY g", "sql")
    assert result.status == "ok" and result.tables[0].row_count == 2
    table = pq.read_table(io.BytesIO(result.tables[0].parquet))
    assert table.column("total").to_pylist() == [3.0, 5.0]


async def test_sql_mode_cannot_read_files_even_unchecked() -> None:
    result = await run("SELECT * FROM read_csv('/etc/passwd')", "sql")
    assert result.status == "error" and result.error_type == "PermissionException"
    assert "disabled by configuration" in result.error


async def test_python_tables_and_stats() -> None:
    code = (
        "df = datasets['ds_1']\n"
        "save_table('by_group', df.groupby('g', as_index=False)['v'].sum())\n"
        "save_stat('mean', df['v'].mean())\n"
        "print('hello')"
    )
    result = await run(code)
    assert result.status == "ok" and result.stats == {"mean": pytest.approx(8 / 3)}
    assert result.tables[0].name == "by_group" and result.stdout.strip() == "hello"


async def test_no_network() -> None:
    code = "import socket\nsocket.create_connection(('1.1.1.1', 53), timeout=3)"
    result = await run(code)
    assert result.status == "error" and result.error_type in ("OSError", "TimeoutError", "gaierror")


async def test_root_filesystem_is_read_only() -> None:
    # /var/tmp is world-writable in the image, so only --read-only can stop this write
    result = await run("open('/var/tmp/x', 'w').write('x')")
    assert result.status == "error" and "Read-only file system" in result.error


async def test_runner_cannot_be_modified() -> None:
    result = await run("open('/opt/runner.py', 'a').write('x')")
    assert result.status == "error" and result.error_type == "PermissionError"


async def test_inputs_are_read_only() -> None:
    result = await run("open('/work/in/ds_1.parquet', 'wb').write(b'x')")
    assert result.status == "error" and "Read-only file system" in result.error


async def test_runs_as_non_root_without_host_files() -> None:
    code = (
        "import os\n"
        "save_stat('uid', os.getuid())\n"
        "save_stat('home', sorted(os.listdir('/home')))\n"
        "save_stat('work', sorted(os.listdir('/work')))"
    )
    result = await run(code)
    assert result.status == "ok"
    assert result.stats["uid"] != 0 and result.stats["home"] == []
    assert result.stats["work"] == ["in", "out"]


async def test_fork_bomb_is_contained() -> None:
    code = (
        "import os\n"
        "pids = []\n"
        "try:\n"
        "    for _ in range(500):\n"
        "        pid = os.fork()\n"
        "        if pid == 0:\n"
        "            import time; time.sleep(30)\n"
        "        pids.append(pid)\n"
        "except OSError as exc:\n"
        "    save_stat('stopped_after', len(pids))\n"
        "    raise SystemExit(0)\n"
    )
    result = await run(code)
    assert result.stats.get("stopped_after", 999) < 64 or result.status in ("timeout", "error")


async def test_memory_hog_is_killed() -> None:
    result = await run("x = bytearray(2_000_000_000)\nsave_stat('n', len(x))")
    assert result.status in ("oom", "error")
    assert result.status == "oom" or "MemoryError" in result.error_type


async def test_infinite_loop_times_out() -> None:
    quick = DockerExecutor(IMAGE, mem_mb=256, timeout_s=4)
    result = await quick.run(SandboxTask("python", "while True:\n    pass", INPUT))
    assert result.status == "timeout"


async def test_too_many_result_tables_refused() -> None:
    code = "\n".join(f"save_table('t{i}', datasets['ds_1'])" for i in range(5))
    result = await run(code)
    assert result.status == "error" and "at most 3" in result.error


# ---- notebook mode: cells share one namespace; figures are captured per cell -----------------

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


async def notebook(*cells: str):  # noqa: ANN201
    return await EXECUTOR.run(SandboxTask("notebook", "", INPUT, cells=tuple(cells)))


async def test_notebook_cells_share_variables_and_report_per_cell() -> None:
    result = await notebook(
        "df = datasets['ds_1']\nprint(len(df))\ndisplay(df.head(2))",
        "save_stat('total', df['v'].sum())\n"
        "save_table('by_group', df.groupby('g', as_index=False)['v'].sum())",
    )
    assert result.status == "ok", result.error
    first, second = result.cells
    assert first.stdout.startswith("3\n") and "g" in first.stdout and first.error == ""
    assert second.stats == {"total": 8.0} and second.tables == ("by_group",)
    assert result.tables[0].name == "by_group" and result.stats == {"total": 8.0}


async def test_notebook_captures_figures_as_png() -> None:
    result = await notebook(
        "import matplotlib.pyplot as plt\nimport seaborn as sns\n"
        "fig, ax = plt.subplots()\nsns.barplot(data=datasets['ds_1'], x='g', y='v', ax=ax)\n"
        "fig2, ax2 = plt.subplots()\nax2.hist(datasets['ds_1']['v'])",
        "x = 1",  # no figure in this cell
        "sns.histplot(datasets['ds_1']['v'])",  # sns and plt are pre-loaded, like in Jupyter
    )
    assert result.status == "ok", result.error
    assert len(result.cells[0].figures) == 2 and result.cells[1].figures == ()
    assert len(result.cells[2].figures) == 1
    assert len(result.figures) == 3
    assert all(f.png.startswith(PNG_SIGNATURE) and len(f.png) < 400_000 for f in result.figures)


async def test_a_failing_cell_stops_later_cells_but_keeps_earlier_outputs() -> None:
    result = await notebook("save_stat('a', 1)", "1 / 0", "save_stat('never', 2)")
    assert result.status == "error" and result.failed_cell == 1
    assert "ZeroDivisionError" in result.error
    assert len(result.cells) == 2 and result.cells[0].stats == {"a": 1}
    assert "ZeroDivisionError" in result.cells[1].error


async def test_figure_count_is_capped() -> None:
    from eagleeye_sandbox.types import MAX_FIGURES

    cell = (
        "import matplotlib.pyplot as plt\n"
        f"for i in range({MAX_FIGURES + 3}):\n    plt.figure()\n    plt.plot([1, 2])"
    )
    result = await notebook(cell)
    assert result.status == "ok" and len(result.figures) == MAX_FIGURES
    assert "figure limit" in result.cells[0].note


async def test_a_mixed_type_text_column_is_saved_as_text() -> None:
    # e.g. a melt/concat leaves ints and strings in one "level" column: still saved
    code = "\n".join(
        [
            "import pandas as pd",
            "save_table('levels', pd.DataFrame({'level': [1, 'high', None], 'n': [3, 4, 5]}))",
        ]
    )
    result = await run(code)
    assert result.status == "ok", result.error
    table = pq.read_table(io.BytesIO(result.tables[0].parquet))
    assert table.column("level").to_pylist() == ["1", "high", None]


async def test_binned_ranges_from_pd_cut_are_saved_as_text() -> None:
    # analysts bin a measure (pd.cut) and save the bins: Parquet can't store interval values
    code = "\n".join(
        [
            "import pandas as pd",
            "df = pd.DataFrame({'speed': [10.0, 14.0, 18.0], 'co2': [1.0, 2.0, 3.0]})",
            "df['band'] = pd.cut(df['speed'], bins=[8, 12, 16, 20])",
            "save_table('banded', df)",
        ]
    )
    result = await run(code)
    assert result.status == "ok", result.error
    table = pq.read_table(io.BytesIO(result.tables[0].parquet))
    assert table.column("band").to_pylist() == ["(8, 12]", "(12, 16]", "(16, 20]"]


async def test_group_labels_in_the_index_are_kept() -> None:
    # groupby(...).mean() puts the group labels in the index; they must not be dropped
    code = "\n".join(
        [
            "import pandas as pd",
            "df = pd.DataFrame({'speed': [10.0, 14.0, 18.0, 19.0], 'co2': [1.0, 2.0, 3.0, 5.0]})",
            "bands = pd.cut(df['speed'], bins=[8, 12, 16, 20])",
            "save_table('by_band', df.groupby(bands, observed=True)['co2'].mean().to_frame())",
        ]
    )
    result = await run(code)
    assert result.status == "ok", result.error
    table = pq.read_table(io.BytesIO(result.tables[0].parquet))
    assert table.column_names == ["speed", "co2"]
    assert table.column("speed").to_pylist() == ["(8, 12]", "(12, 16]", "(16, 20]"]
    assert table.column("co2").to_pylist() == [1.0, 2.0, 4.0]


async def test_a_filtered_table_gains_no_row_number_column() -> None:
    code = "df = datasets['ds_1']\nsave_table('big', df[df['v'] > 1.5])"
    result = await run(code)
    assert result.status == "ok", result.error
    table = pq.read_table(io.BytesIO(result.tables[0].parquet))
    assert table.column_names == ["g", "v"] and table.num_rows == 2
