"""Wake function for the demo machine (Phase 7B). One function, four kinds of event:

  function URL (POST, x-wake-secret)   start the machine if allowed → {"state": ...}
  EC2 state change (EventBridge)       keep today's running time for the daily cap
  {"action": "enforce"} (hourly)       stop the machine once today's cap is used up
  {"action": "nightly_stop"} (daily)   safety stop

Running time is kept in one SSM parameter: {"day": "YYYY-MM-DD", "seconds": n, "started_at": t}.
Starting is refused (HTTP 429) beyond DAILY_CAP_S of running time per UTC day.
"""

import hmac
import json
import os
import time
from datetime import UTC, datetime
from typing import Any

INSTANCE_ID = os.environ.get("INSTANCE_ID", "")
RUNTIME_PARAM = os.environ.get("RUNTIME_PARAM", "")
DAILY_CAP_S = int(os.environ.get("DAILY_CAP_S", str(6 * 3600)))
WAKE_SECRET = os.environ.get("WAKE_SECRET", "")


def _clients() -> tuple[Any, Any]:  # pragma: no cover - replaced in tests
    import boto3

    return boto3.client("ec2"), boto3.client("ssm")


# ---- running-time bookkeeping (pure) ---------------------------------------------------------


def today(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")


def used_today(record: dict, now: float) -> float:
    """Seconds the machine has run today, including the current run."""
    if record.get("day") != today(now):
        started = float(record.get("started_at") or 0)
        midnight = datetime.fromtimestamp(now, UTC).replace(hour=0, minute=0, second=0).timestamp()
        return now - max(started, midnight) if started else 0.0
    running = now - float(record["started_at"]) if record.get("started_at") else 0.0
    return float(record.get("seconds", 0)) + running


def on_state(record: dict, state: str, now: float) -> dict:
    """The new record after the machine reached `state` ("running" or "stopped")."""
    day = today(now)
    if state == "running":  # earlier runs today stay counted; this run counts from now
        before = float(record.get("seconds", 0)) if record.get("day") == day else 0.0
        return {"day": day, "seconds": before, "started_at": now}
    return {"day": day, "seconds": used_today(record, now), "started_at": 0}


# ---- AWS side ----------------------------------------------------------------------------------


def _read(ssm: Any) -> dict:
    raw = ssm.get_parameter(Name=RUNTIME_PARAM)["Parameter"]["Value"]
    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        record = {}
    return record if isinstance(record, dict) else {}


def _write(ssm: Any, record: dict) -> None:
    ssm.put_parameter(Name=RUNTIME_PARAM, Value=json.dumps(record), Type="String", Overwrite=True)


def _state(ec2: Any) -> str:
    reservations = ec2.describe_instances(InstanceIds=[INSTANCE_ID])["Reservations"]
    return reservations[0]["Instances"][0]["State"]["Name"]


def _reply(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(body),
    }


def wake(event: dict, ec2: Any, ssm: Any, now: float) -> dict:
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    if method != "POST":
        return _reply(405, {"error": "POST only"})
    given = {k.lower(): v for k, v in (event.get("headers") or {}).items()}.get("x-wake-secret", "")
    if not WAKE_SECRET or not hmac.compare_digest(given.encode(), WAKE_SECRET.encode()):
        return _reply(403, {"error": "forbidden"})
    state = _state(ec2)
    if state == "running":
        return _reply(200, {"state": "running"})
    if state in ("pending", "stopping", "shutting-down"):
        return _reply(200, {"state": "starting"})  # the page keeps polling and asks again
    if state != "stopped":
        return _reply(503, {"error": f"machine is {state}"})
    if used_today(_read(ssm), now) >= DAILY_CAP_S:
        return _reply(429, {"error": "daily running-time cap reached"})
    ec2.start_instances(InstanceIds=[INSTANCE_ID])
    return _reply(200, {"state": "starting"})


def handler(event: dict, context: object = None) -> dict:
    ec2, ssm = _clients()
    now = time.time()
    if "requestContext" in event:  # function URL
        return wake(event, ec2, ssm, now)
    if event.get("source") == "aws.ec2":
        state = event.get("detail", {}).get("state", "")
        if event.get("detail", {}).get("instance-id") == INSTANCE_ID and state in (
            "running",
            "stopped",
        ):
            _write(ssm, on_state(_read(ssm), state, now))
        return {"ok": True}
    action = event.get("action")
    if action == "nightly_stop" or (
        action == "enforce" and used_today(_read(ssm), now) >= DAILY_CAP_S
    ):
        if _state(ec2) in ("running", "pending"):
            ec2.stop_instances(InstanceIds=[INSTANCE_ID])
            return {"stopped": True}
    return {"stopped": False}
