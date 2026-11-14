"""AnalysisExecutor backed by `docker run`: one short-lived container per task (C6 §4).

The container gets: no network, a read-only root filesystem, no Linux capabilities, a
non-root user (set in the image), CPU / memory / process caps, inputs mounted read-only
and a single writable output folder. A hard timeout kills it by name.
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess  # noqa: S404 — fixed argv, never a shell
import tempfile
import time
import uuid
from pathlib import Path

from eagleeye_sandbox.result_io import parse_result, task_spec
from eagleeye_sandbox.types import SandboxResult, SandboxTask

logger = logging.getLogger(__name__)

KILL_GRACE_S = 10
OOM_EXIT_CODE = 137
START_FAILURE = "The analysis sandbox could not run this task."


class DockerExecutor:
    def __init__(
        self, image: str, mem_mb: int = 1024, timeout_s: int = 60, docker: str = "docker"
    ) -> None:
        self._image = image
        self._mem_mb = mem_mb
        self._timeout_s = timeout_s
        self._docker = docker

    async def available(self) -> bool:
        return await asyncio.to_thread(self._image_present)

    def _image_present(self) -> bool:
        try:
            proc = subprocess.run(  # noqa: S603
                [self._docker, "image", "inspect", self._image, "--format", "{{.Id}}"],
                capture_output=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    async def run(self, task: SandboxTask) -> SandboxResult:
        return await asyncio.to_thread(self._run_sync, task)

    def _command(self, name: str, in_dir: Path, out_dir: Path) -> list[str]:
        mem = f"{self._mem_mb}m"
        return [
            self._docker,
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "64",
            "--memory",
            mem,
            "--memory-swap",
            mem,  # equal to --memory: no swap
            "--cpus",
            "1",
            "--tmpfs",
            "/tmp:rw,size=64m,mode=1777",  # noqa: S108 — path inside the container
            "-v",
            f"{in_dir}:/work/in:ro",
            "-v",
            f"{out_dir}:/work/out:rw",
            self._image,
        ]

    def _kill(self, name: str) -> None:
        try:
            subprocess.run(  # noqa: S603
                [self._docker, "kill", name], capture_output=True, timeout=KILL_GRACE_S, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            logger.exception("failed to kill sandbox container %s", name)

    def _run_sync(self, task: SandboxTask) -> SandboxResult:
        workdir = Path(tempfile.mkdtemp(prefix="eagleeye-sbx-"))
        in_dir, out_dir = workdir / "in", workdir / "out"
        name = f"eagleeye-sbx-{uuid.uuid4().hex[:12]}"
        started = time.monotonic()
        try:
            in_dir.mkdir()
            out_dir.mkdir()
            os.chmod(out_dir, 0o777)  # noqa: S103 — the container's non-root user must write here
            inputs = []
            for item in task.inputs:
                (in_dir / f"{item.name}.parquet").write_bytes(item.parquet)
                inputs.append({"name": item.name, "file": f"{item.name}.parquet"})
            spec = task_spec(task, inputs)
            (in_dir / "task.json").write_text(json.dumps(spec), encoding="utf-8")
            try:
                proc = subprocess.run(  # noqa: S603
                    self._command(name, in_dir, out_dir),
                    capture_output=True,
                    timeout=self._timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                self._kill(name)
                return SandboxResult(
                    "timeout",
                    error=f"The analysis took longer than {self._timeout_s}s and was stopped.",
                    duration_ms=_ms(started),
                )
            except OSError:
                logger.exception("docker is not runnable")
                return SandboxResult("unavailable", error=START_FAILURE)
            return self._collect(proc, out_dir, _ms(started))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _collect(
        self, proc: subprocess.CompletedProcess[bytes], out_dir: Path, duration_ms: int
    ) -> SandboxResult:
        result_file = out_dir / "result.json"
        if not result_file.is_file():
            if proc.returncode == OOM_EXIT_CODE:
                return SandboxResult(
                    "oom",
                    error=f"The analysis ran out of memory ({self._mem_mb} MB).",
                    duration_ms=duration_ms,
                )
            logger.error(
                "sandbox exited %s without a result: %s",
                proc.returncode,
                proc.stderr.decode("utf-8", "replace")[-800:],
            )
            return SandboxResult("unavailable", error=START_FAILURE, duration_ms=duration_ms)
        try:
            body = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return SandboxResult("error", error=START_FAILURE, duration_ms=duration_ms)

        def read(name: str) -> bytes | None:  # basename only: stays inside out_dir
            path = out_dir / name
            return path.read_bytes() if name and path.is_file() else None

        return parse_result(body, read, duration_ms)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
