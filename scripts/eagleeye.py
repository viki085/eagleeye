"""Start, stop and check the whole EagleEye stack on Windows, macOS and Linux.

Run through the wrappers (they supply psutil via uv; nothing to install):
  Windows:      scripts\\start.cmd [--skip-infra] [--onboard]
                scripts\\stop.cmd  [--infra] [--force] [--drain-timeout N]
                scripts\\status.cmd
  macOS/Linux:  scripts/start.sh, scripts/stop.sh, scripts/status.sh  (same options)

start  infra (Docker services, Supabase + migrations, sandbox image) -> API + data gateway ->
       agent + ingest workers -> web; waits until each is healthy. Safe to run twice.
stop   web + API first (no new work), waits until in-flight answers/uploads finish, then the
       workers and gateway. --infra also stops Docker services and Supabase (data is kept).
Only EagleEye's own processes are touched (matched by command line). Logs: logs/<service>.log
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
COMPOSE = ROOT / "infra" / "docker-compose.yml"
WINDOWS = os.name == "nt"


def exe(name: str) -> str:
    found = shutil.which(name)
    if not found:
        sys.exit(f"'{name}' is not installed or not on PATH.")
    return found


SERVICES = [
    {"name": "api", "match": "app.main:app --app-dir apps/api", "health": "http://127.0.0.1:8000/v1/health/live",
     "cwd": ROOT, "cmd": ["uv", "run", "--package", "eagleeye-api", "uvicorn", "app.main:app",
                          "--app-dir", "apps/api", "--port", "8000"]},
    {"name": "gateway", "match": "gateway.main:app --app-dir apps/data-gateway", "health": "http://127.0.0.1:8100/health",
     "cwd": ROOT, "cmd": ["uv", "run", "--package", "eagleeye-data-gateway", "uvicorn", "gateway.main:app",
                          "--app-dir", "apps/data-gateway", "--port", "8100"]},
    {"name": "agent", "match": "agent_worker.celery_app", "health": None,
     "cwd": ROOT, "cmd": ["uv", "run", "--package", "eagleeye-agent-worker", "celery", "-A", "agent_worker.celery_app",
                          "worker", "--pool=threads", "--concurrency=8", "-Q", "agent", "-l", "info", "-n", "agent@%h"]},
    {"name": "ingest", "match": "ingest_worker.celery_app", "health": None,
     "cwd": ROOT, "cmd": ["uv", "run", "--package", "eagleeye-ingest-worker", "celery", "-A", "ingest_worker.celery_app",
                          "worker", "--pool=solo", "-Q", "ingest", "-l", "info", "-n", "ingest@%h"]},
    # the dev server's node processes all run from apps/web
    {"name": "web", "match": str(ROOT / "apps" / "web"), "health": "http://localhost:3000/",
     "cwd": ROOT / "apps" / "web", "cmd": ["npm", "run", "dev"]},
]
BY_NAME = {s["name"]: s for s in SERVICES}


def say(text: str) -> None:
    print(f"==> {text}", flush=True)


def ok(text: str) -> None:
    print(f"    [ok] {text}", flush=True)


def warn(text: str) -> None:
    print(f"    [!]  {text}", flush=True)


# --- processes ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


def find(service: dict) -> list[psutil.Process]:
    needle = _norm(service["match"])
    found = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if p.pid != os.getpid() and needle in _norm(cmd):
            found.append(p)
    return found


def running(service: dict) -> bool:
    return bool(find(service))


def stop_service(service: dict, grace: float = 15.0) -> None:
    procs = find(service)
    if not procs:
        ok(f"{service['name']} was not running")
        return
    tree: dict[int, psutil.Process] = {}
    for p in procs:
        try:
            for child in [p, *p.children(recursive=True)]:
                tree[child.pid] = child
        except psutil.NoSuchProcess:
            continue
    alive = list(tree.values())
    for p in alive:  # SIGTERM on macOS/Linux = graceful (Celery warm shutdown); Windows: terminate
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(alive, timeout=grace)
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(alive, timeout=5)
    ok(f"{service['name']} stopped")


def start_service(service: dict) -> None:
    if running(service):
        ok(f"{service['name']} is already running")
        return
    LOGS.mkdir(exist_ok=True)
    log = open(LOGS / f"{service['name']}.log", "w", encoding="utf-8")  # noqa: SIM115 - handed to the child
    cmd = [exe(service["cmd"][0]), *service["cmd"][1:]]
    kwargs: dict = {"cwd": service["cwd"], "stdout": log, "stderr": subprocess.STDOUT,
                    "stdin": subprocess.DEVNULL}
    if WINDOWS:
        kwargs["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NO_WINDOW)
    else:
        kwargs["start_new_session"] = True  # survives this terminal closing
    subprocess.Popen(cmd, **kwargs)  # noqa: S603 - fixed command list
    print(f"    starting {service['name']} (logs/{service['name']}.log)", flush=True)


# --- health ------------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        return None


def http_ok(url: str) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=5) as resp:  # noqa: S310 - localhost
            return resp.status < 400
    except urllib.error.HTTPError as exc:
        return 300 <= exc.code < 400  # Next.js + Clerk redirect a signed-out page: healthy
    except (urllib.error.URLError, OSError):
        return False


def healthy(service: dict) -> bool:
    if service["health"]:
        return http_ok(service["health"])
    logs = list(LOGS.glob(f"{service['name']}*.log"))  # Celery logs "ready." once connected to the broker
    if any("ready." in f.read_text(encoding="utf-8", errors="ignore") for f in logs):
        return True
    return running(service) and not logs  # started outside this script


def wait_for(service: dict, timeout: int) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if healthy(service):
            ok(f"{service['name']} is healthy")
            return True
        time.sleep(1)
    warn(f"{service['name']} did not become ready in {timeout} s (see logs/{service['name']}.log)")
    return False


# --- infra -------------------------------------------------------------------------------

def run_logged(cmd: list[str], log_name: str) -> int:
    LOGS.mkdir(exist_ok=True)
    with open(LOGS / log_name, "w", encoding="utf-8") as log:
        return subprocess.call([exe(cmd[0]), *cmd[1:]], cwd=ROOT, stdout=log,  # noqa: S603
                               stderr=subprocess.STDOUT)


def start_infra() -> None:
    say("Starting infrastructure (Docker services)")
    if run_logged(["docker", "info"], "docker-info.log") != 0:
        sys.exit("Docker is not running. Start Docker and try again.")
    if run_logged(["docker", "compose", "-f", str(COMPOSE), "up", "-d"], "docker-compose.log") != 0:
        sys.exit("docker compose failed; see logs/docker-compose.log")
    ok("Redis, Qdrant, SeaweedFS and the demo warehouse are up")
    if run_logged(["docker", "image", "inspect", "eagleeye-sandbox:1"], "docker-image.log") != 0:
        say("Building the analysis sandbox image (first run only)")
        if run_logged(["docker", "build", "-t", "eagleeye-sandbox:1", str(ROOT / "infra" / "sandbox")],
                      "sandbox-build.log") != 0:
            warn("Sandbox build failed (logs/sandbox-build.log): data analysis will be unavailable")
    say("Starting Supabase (Postgres) and applying migrations")
    if run_logged(["npx", "supabase", "status"], "supabase-status.log") != 0:
        if run_logged(["npx", "supabase", "start"], "supabase-start.log") != 0:
            sys.exit("Supabase did not start; see logs/supabase-start.log")
    if run_logged(["npx", "supabase", "migration", "up"], "supabase-migrate.log") != 0:
        sys.exit("Migrations failed; see logs/supabase-migrate.log")
    ok("Supabase is up and migrations are applied")


def stop_infra() -> None:
    say("Stopping Supabase and the Docker services (data is kept)")
    if run_logged(["npx", "supabase", "stop"], "supabase-stop.log") == 0:
        ok("Supabase stopped")
    else:
        warn("Supabase did not stop cleanly; see logs/supabase-stop.log")
    if run_logged(["docker", "compose", "-f", str(COMPOSE), "stop"], "docker-stop.log") == 0:
        ok("Docker services stopped (volumes kept)")
    else:
        warn("docker compose stop failed; see logs/docker-stop.log")


# --- drain -------------------------------------------------------------------------------

def in_flight() -> dict | None:
    try:
        out = subprocess.run(  # noqa: S603
            [exe("uv"), "run", "--package", "eagleeye-api", "python", "scripts/drain_status.py"],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        line = [x for x in out.stdout.splitlines() if x.strip().startswith("{")][-1]
        status = json.loads(line)
        return None if status.get("error") else status
    except (IndexError, ValueError, subprocess.SubprocessError, OSError):
        return None


def drain(timeout: int) -> None:
    say(f"Waiting for in-flight work to finish (up to {timeout} s)")
    deadline, last = time.time() + timeout, ""
    while True:
        s = in_flight()
        if s is None:
            warn("Could not read work status (database or Redis down?); stopping workers now")
            return
        queued = s["agent_queue"] + s["ingest_queue"]
        uploads = s["documents"] + s["datasets"]
        if s["runs"] + queued + uploads == 0:
            ok("No work in flight")
            return
        text = f"answers in progress: {s['runs']}, queued tasks: {queued}, uploads processing: {uploads}"
        if text != last:
            print(f"    {text}", flush=True)
            last = text
        if time.time() >= deadline:
            warn(f"Timed out with work still in flight ({text}); unfinished answers can be retried")
            return
        time.sleep(3)


# --- commands ----------------------------------------------------------------------------

def cmd_start(args: argparse.Namespace) -> int:
    for tool in ("docker", "uv", "node", "npm"):
        exe(tool)
    if not (ROOT / ".env").exists():
        sys.exit(".env is missing. Copy .env.example to .env and fill in the keys first.")
    began = time.time()
    if not args.skip_infra:
        start_infra()
    if args.onboard:
        say("Onboarding the demo warehouse into the catalog (one-time)")
        run_logged(["uv", "run", "--package", "eagleeye-catalog", "python", "-m", "eagleeye_catalog.cli",
                    "onboard", "acme_warehouse"], "onboard.log")
    results: dict[str, bool] = {}
    for group, title, timeout in ((("api", "gateway"), "API and data gateway", 90),
                                  (("agent", "ingest"), "agent and ingest workers", 90),
                                  (("web",), "web app", 120)):
        say(f"Starting the {title}")
        for name in group:
            start_service(BY_NAME[name])
        for name in group:
            results[name] = wait_for(BY_NAME[name], timeout)
    print(f"\nEagleEye status (started in {int(time.time() - began)} s)")
    for name, up in results.items():
        print(f"  {name:8} {'up' if up else 'NOT READY - see logs/' + name + '.log'}")
    print("\n  App:      http://localhost:3000\n  Status:   http://localhost:3000/status"
          "\n  API docs: http://localhost:8000/docs")
    return 0 if all(results.values()) else 1


def cmd_stop(args: argparse.Namespace) -> int:
    say("Stopping the web app and the API (no new work is accepted)")
    stop_service(BY_NAME["web"])
    stop_service(BY_NAME["api"])
    if args.force:
        warn("--force: not waiting for in-flight work")
    elif running(BY_NAME["agent"]) or running(BY_NAME["ingest"]):
        drain(args.drain_timeout)
    say("Stopping the workers and the data gateway")
    for name in ("agent", "ingest", "gateway"):
        stop_service(BY_NAME[name], grace=30.0)
    if args.infra:
        stop_infra()
    else:
        print("    Docker services and Supabase left running (use --infra to stop them too).")
    still = [s["name"] for s in SERVICES if running(s)]
    print("\nEagleEye is stopped." if not still else f"\nStill running: {', '.join(still)}")
    return 0 if not still else 1


def cmd_status(_: argparse.Namespace) -> int:
    for s in SERVICES:
        state = ("healthy" if healthy(s) else "starting/unhealthy") if running(s) else "stopped"
        print(f"  {s['name']:8} {state}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Start/stop the EagleEye stack.")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("start", help="start everything and wait until healthy")
    p.add_argument("--skip-infra", action="store_true", help="Docker and Supabase are already up")
    p.add_argument("--onboard", action="store_true", help="one-time catalog onboarding of the demo warehouse")
    p.set_defaults(func=cmd_start)
    p = sub.add_parser("stop", help="safe shutdown (finishes in-flight work first)")
    p.add_argument("--infra", action="store_true", help="also stop Docker services and Supabase")
    p.add_argument("--force", action="store_true", help="do not wait for in-flight work")
    p.add_argument("--drain-timeout", type=int, default=180, help="seconds to wait for in-flight work")
    p.set_defaults(func=cmd_stop)
    sub.add_parser("status", help="show what is running").set_defaults(func=cmd_status)
    args = ap.parse_args()
    if not WINDOWS:
        signal.signal(signal.SIGINT, signal.default_int_handler)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
