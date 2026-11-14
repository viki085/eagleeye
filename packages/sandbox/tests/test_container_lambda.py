"""The Lambda sandbox against its real image, through the local Lambda emulator (Phase 7A).

Run the function locally first (read-only root, non-root, like AWS):
  docker run -d --name ee-sandbox-lambda --user 10001:10001 --read-only \
    --tmpfs /tmp:rw,size=512m --network eagleeye_default -p 9000:8080 eagleeye-sandbox-lambda:1
Skipped when it isn't running. Network isolation can't be reproduced here (the local function
needs the storage container); it is tested against the real function in the cloud (7B).
"""

import asyncio
import io
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from eagleeye_core.config import Settings
from eagleeye_sandbox.lambda_executor import build_lambda_executor
from eagleeye_sandbox.types import SandboxInput, SandboxTask

pytestmark = pytest.mark.integration

SETTINGS = Settings(
    _env_file=None,
    sandbox_lambda_function="function",  # the emulator serves its one function under this name
    sandbox_lambda_endpoint_url=os.environ.get(
        "SANDBOX_LAMBDA_TEST_ENDPOINT", "http://localhost:9000"
    ),
    sandbox_transfer_endpoint_url=os.environ.get(
        "SANDBOX_TRANSFER_TEST_ENDPOINT", "http://seaweedfs:8333"
    ),
)
EXECUTOR = build_lambda_executor(SETTINGS, mem_mb=768, timeout_s=30)

if not asyncio.run(EXECUTOR.available()):
    pytest.skip("local Lambda sandbox not running", allow_module_level=True)


def parquet() -> bytes:
    buf = io.BytesIO()
    pq.write_table(pa.table({"g": ["a", "a", "b"], "v": [1.0, 2.0, 5.0]}), buf)
    return buf.getvalue()


INPUT = (SandboxInput("ds_1", parquet(), ({"name": "g", "type": "VARCHAR"},)),)


async def run(code: str, mode: str = "python", executor=EXECUTOR):  # noqa: ANN001, ANN201
    return await executor.run(SandboxTask(mode, code, INPUT))  # type: ignore[arg-type]


async def test_sql_mode_returns_a_table() -> None:
    result = await run("SELECT g, SUM(v) AS total FROM ds_1 GROUP BY g ORDER BY g", "sql")
    assert result.status == "ok", result.error
    table = pq.read_table(io.BytesIO(result.tables[0].parquet))
    assert table.column("total").to_pylist() == [3.0, 5.0]


async def test_python_tables_and_stats() -> None:
    code = (
        "df = datasets['ds_1']\n"
        "save_table('by_group', df.groupby('g', as_index=False)['v'].sum())\n"
        "save_stat('mean', df['v'].mean())"
    )
    result = await run(code)
    assert result.status == "ok", result.error
    assert result.stats == {"mean": pytest.approx(8 / 3)} and result.tables[0].name == "by_group"


async def test_notebook_with_figures() -> None:
    cells = (
        "df = datasets['ds_1']\ndisplay(df.head(2))",
        "sns.barplot(data=df, x='g', y='v')\nsave_stat('n', len(df))",
    )
    result = await EXECUTOR.run(SandboxTask("notebook", "", INPUT, cells=cells))
    assert result.status == "ok", result.error
    assert result.cells[1].stats == {"n": 3} and len(result.figures) == 1
    assert result.figures[0].png.startswith(b"\x89PNG\r\n\x1a\n")


async def test_runs_as_non_root_without_aws_credentials() -> None:
    code = (
        "import os\n"
        "save_stat('uid', os.getuid())\n"
        "save_stat('aws', sorted(k for k in os.environ if k.startswith('AWS')))"
    )
    result = await run(code)
    assert result.status == "ok", result.error
    assert result.stats["uid"] != 0 and result.stats["aws"] == []


async def test_root_filesystem_is_read_only() -> None:
    result = await run("open('/var/task/runner.py', 'a').write('x')")
    assert result.status == "error" and result.error_type in ("OSError", "PermissionError")


async def test_nothing_survives_into_the_next_invocation() -> None:
    first = (
        "import subprocess, pathlib\n"
        "pathlib.Path('/tmp/leftover').write_text('secret')\n"
        "subprocess.Popen(['sleep', '60'])\n"
        "subprocess.Popen(['sleep', '61'], start_new_session=True)\n"  # leaves the process group
        "save_stat('ok', 1)"
    )
    assert (await run(first)).status == "ok"
    second = (
        "import os, pathlib\n"
        "save_stat('leftover', pathlib.Path('/tmp/leftover').exists())\n"
        "names = []\n"
        "for pid in os.listdir('/proc'):\n"
        "    if pid.isdigit():\n"
        "        try:\n"
        "            names.append(open(f'/proc/{pid}/comm').read().strip())\n"
        "        except OSError:\n"
        "            pass\n"
        "save_stat('sleepers', names.count('sleep'))"
    )
    result = await run(second)
    assert result.status == "ok", result.error
    assert result.stats == {"leftover": False, "sleepers": 0}


async def test_memory_hog_is_stopped() -> None:
    result = await run("x = bytearray(3_000_000_000)\nsave_stat('n', len(x))")
    assert result.status == "oom"


async def test_infinite_loop_times_out() -> None:
    quick = build_lambda_executor(SETTINGS, mem_mb=512, timeout_s=4)
    result = await run("while True:\n    pass", executor=quick)
    assert result.status == "timeout"


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
        "except OSError:\n"
        "    save_stat('stopped_after', len(pids))\n"
        "    raise SystemExit(0)\n"
    )
    result = await run(code)
    assert result.stats.get("stopped_after", 999) < 256 or result.status in ("timeout", "error")


async def test_a_realistic_file_reads_without_starving_threads() -> None:
    """Regression: a 2,000-row Parquet made Arrow start threads beyond the process limit and
    the child deadlocked until the timeout (the tiny test file never triggered it)."""
    import numpy as np

    n = 5000
    buf = io.BytesIO()
    pq.write_table(
        pa.table(
            {
                "voyage": [f"V{i}" for i in range(n)],
                "speed": np.random.default_rng(1).normal(16, 2, n),
                "fuel": np.random.default_rng(2).normal(80, 10, n),
                "route": [["AEX", "AMX", "TAT"][i % 3] for i in range(n)],
            }
        ),
        buf,
    )
    big = (SandboxInput("ds_1", buf.getvalue()),)
    cells = (
        "df = datasets['ds_1']\nprint(df.shape)\ndisplay(df.describe())",
        "sns.scatterplot(data=df.sample(500, random_state=1), x='speed', y='fuel', hue='route')",
    )
    result = await EXECUTOR.run(SandboxTask("notebook", "", big, cells=cells))
    assert result.status == "ok", result.error
    assert result.cells[0].stdout.startswith("(5000, 4)") and len(result.figures) == 1
