"""AWS Lambda entry point for the analysis sandbox (Phase 7A; C10 §2.4).

The same runner.py as the Docker sandbox does the work. This handler only moves files:
  event  {task: <runner task spec>, inputs: [{name, file, url}], upload: {url, fields, prefix},
          timeout_s, mem_mb}            or {ping: true}
  return {result: <runner result.json>, uploaded: [file, ...]}   or {pong: true}

Inputs are fetched from single-use pre-signed GET links; outputs go up through a pre-signed
POST that only accepts keys under one prefix and a capped size. The links never reach the
untrusted code: it runs in a child process that only sees local folders.

Lambda reuses a warm environment for later invocations, possibly another user's, so every
invocation starts clean and leaves nothing behind: /tmp is wiped before and after, the code
runs in a fresh process in its own process group (killed afterwards, so nothing it started
survives), with memory, process and file-size limits.
"""

import contextlib
import ctypes
import json
import os
import resource
import shutil
import signal
import subprocess  # noqa: S404 - fixed argv, never a shell
import sys
import urllib.request
import uuid
from pathlib import Path

WORK = Path("/tmp/sbx")  # noqa: S108 - Lambda's only writable folder
IN_DIR, OUT_DIR = WORK / "in", WORK / "out"
MPL_CACHE = Path("/tmp/matplotlib")  # noqa: S108
RUNNER = Path(__file__).with_name("runner.py")
MAX_FILE_BYTES = 20 * 1024 * 1024
# processes AND threads of the sandbox user; Arrow and its allocator start several threads
# (the container reports every host CPU), so 64 starved them and the child deadlocked
MAX_PROCESSES = 256
HTTP_TIMEOUT_S = 30
KEEP = {MPL_CACHE.name}  # the font cache copied from the image may stay between runs
PR_SET_CHILD_SUBREAPER = 36


def _wipe_tmp() -> None:
    for entry in Path("/tmp").iterdir():  # noqa: S108
        if entry.name in KEEP:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)


def _download(url: str, dest: Path) -> None:
    if not url.startswith(("https://", "http://")):
        raise ValueError("input link must be http(s)")
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as resp:  # noqa: S310 - checked above
        dest.write_bytes(resp.read(MAX_FILE_BYTES + 1)[: MAX_FILE_BYTES + 1])
    if dest.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("input too large")


def _upload(upload: dict, name: str, data: bytes) -> None:
    """multipart/form-data POST of one file to the pre-signed form (stdlib only)."""
    boundary = uuid.uuid4().hex
    fields = {**upload["fields"], "key": f"{upload['prefix']}{name}"}
    body = b"".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, v in fields.items()
    )
    body += (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    req = urllib.request.Request(  # noqa: S310 - pre-signed URL from the executor
        upload["url"],
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:  # noqa: S310
        if resp.status not in (200, 201, 204):
            raise OSError(f"upload failed: {resp.status}")


def _become_subreaper() -> None:
    """Orphans of the analysis code are re-parented to this process (not PID 1), so they can
    always be found, killed and reaped, even if they left the process group."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0)
    except (OSError, AttributeError):
        pass  # not Linux (unit tests): descendants are still found through /proc


def _descendants(root: int) -> set[int]:
    parents: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        # "pid (comm) state ppid ...": comm may contain spaces, so split after the last ")"
        parents[int(entry.name)] = int(stat.rsplit(")", 1)[1].split()[1])
    found: set[int] = set()
    frontier = {root}
    while frontier:
        frontier = {pid for pid, ppid in parents.items() if ppid in frontier} - found
        found |= frontier
    return found


def _kill_leftovers() -> None:
    """Kills every process the analysis code started (by ancestry, not process group) and reaps
    them, so nothing — not even a zombie — reaches the next invocation."""
    for _ in range(5):
        pids = _descendants(os.getpid())
        if not pids:
            break
        for pid in pids:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)
        _reap()
    _reap()


def _reap() -> None:
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def _limits(mem_mb: int):  # noqa: ANN202
    def apply() -> None:
        # RLIMIT_DATA counts memory actually written (heap and private mappings). Not RLIMIT_AS:
        # DuckDB's allocator reserves a huge address range up front and crashes under it. The
        # function's own memory setting stays the hard cap for the whole environment.
        memory = mem_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_DATA, (memory, memory))
        resource.setrlimit(resource.RLIMIT_NPROC, (MAX_PROCESSES, MAX_PROCESSES))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_BYTES, MAX_FILE_BYTES))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return apply


def _run_child(timeout_s: int, mem_mb: int) -> str:
    """Runs runner.py in a fresh process; returns 'ok', 'timeout' or 'crashed'."""
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",  # noqa: S108
        "SANDBOX_IN_DIR": str(IN_DIR),
        "SANDBOX_OUT_DIR": str(OUT_DIR),
        "MPLBACKEND": "Agg",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "ARROW_IO_THREADS": "2",
    }  # deliberately no AWS credentials or other Lambda environment
    proc = subprocess.Popen(  # noqa: S603 - fixed argv
        [sys.executable, str(RUNNER)],
        env=env,
        cwd=str(WORK),
        start_new_session=True,
        preexec_fn=_limits(mem_mb),  # noqa: PLW1509 - limits must apply before exec
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        proc.wait(timeout=timeout_s)
        return "ok"
    except subprocess.TimeoutExpired:
        return "timeout"
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)  # the child's group first
        proc.wait()
        _kill_leftovers()  # then anything that escaped the group


def _outputs(result: dict) -> list[str]:
    names = [str(t.get("file", "")) for t in result.get("tables", [])]
    names += [str(f.get("file", "")) for f in result.get("figures", [])]
    return [n for n in names if n and "/" not in n and "\\" not in n and (OUT_DIR / n).is_file()]


_become_subreaper()


def handler(event: dict, context: object) -> dict:  # noqa: ARG001 - Lambda signature
    if event.get("ping"):
        return {"pong": True}
    _wipe_tmp()
    try:
        IN_DIR.mkdir(parents=True)
        OUT_DIR.mkdir()
        inputs = []
        for item in event["inputs"]:
            name, file = str(item["name"]), Path(str(item["file"])).name
            _download(str(item["url"]), IN_DIR / file)
            inputs.append({"name": name, "file": file})
        (IN_DIR / "task.json").write_text(json.dumps({**event["task"], "inputs": inputs}))
        state = _run_child(int(event.get("timeout_s", 60)), int(event.get("mem_mb", 1024)))
        result_file = OUT_DIR / "result.json"
        if state == "timeout":
            return {"result": {"status": "timeout"}, "uploaded": []}
        if not result_file.is_file():
            return {"result": {"status": "crashed"}, "uploaded": []}
        result = json.loads(result_file.read_text(encoding="utf-8"))
        uploaded = []
        for name in _outputs(result):
            _upload(event["upload"], name, (OUT_DIR / name).read_bytes())
            uploaded.append(name)
        return {"result": result, "uploaded": uploaded}
    finally:
        _wipe_tmp()
