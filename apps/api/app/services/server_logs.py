"""Server logs for the admin console (System tab), read from CloudWatch Logs Insights.

The demo machine's containers write to one log group (one stream per container, Docker's
awslogs driver). Newest first, at most MAX_EVENTS lines, filtered by service, level and text.
Every filter value is checked against a fixed list or escaped before it goes into the query.
Without a log group (a laptop) the panel says logs are not available here.
"""

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

import boto3

Service = Literal["all", "api", "gateway", "agent-worker", "ingest-worker"]
Window = Literal["15m", "1h", "6h", "24h"]
Level = Literal["all", "warning", "error"]

WINDOW_MINUTES = {"15m": 15, "1h": 60, "6h": 360, "24h": 1440}
LEVELS = {
    "all": None,
    "warning": ["WARNING", "ERROR", "CRITICAL"],
    "error": ["ERROR", "CRITICAL"],
}
STREAM_PREFIX = "eagleeye-demo-"  # Docker's awslogs tag: the container name
MAX_EVENTS = 300
MAX_QUERY_CHARS = 100
MAX_MESSAGE_CHARS = 4000
POLL_S = 0.5
TIMEOUT_S = 12.0


class LogsUnavailableError(Exception):
    """CloudWatch could not be queried (permissions, network, or the query timed out)."""


@dataclass(frozen=True)
class LogQuery:
    service: Service = "all"
    window: Window = "1h"
    level: Level = "all"
    text: str = ""
    hide_health: bool = True  # the health checks every few seconds drown everything else


def _literal(text: str) -> str:
    """A safe Insights string literal: printable characters only, quotes and backslashes
    escaped, length capped."""
    clean = "".join(ch for ch in text if ch.isprintable())[:MAX_QUERY_CHARS]
    return '"' + clean.replace("\\", "\\\\").replace('"', '\\"') + '"'


# plain-text lines (uvicorn, celery) start with their level: "WARNING:  ..."
_PLAIN_LEVEL = re.compile(r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL):?\s+")
HEALTH_PATHS = ("GET /v1/health", "GET /health")


def build_query(q: LogQuery) -> str:
    lines = ["fields @timestamp, @logStream, @message, level"]
    if q.service != "all":
        lines.append(f"| filter @logStream like {_literal(STREAM_PREFIX + q.service + '-')}")
    if q.hide_health:
        lines.append(
            "| filter " + " and ".join(f"@message not like {_literal(p)}" for p in HEALTH_PATHS)
        )
    levels = LEVELS[q.level]
    if levels:
        # JSON lines have a level field; plain-text lines start with it (a fixed pattern)
        names = "|".join(levels)
        lines.append(
            f"| filter level in [{', '.join(_literal(v) for v in levels)}]"
            f" or @message like /^({names}):/"
        )
    if q.text.strip():
        lines.append(f"| filter @message like {_literal(q.text.strip())}")
    lines += ["| sort @timestamp desc", f"| limit {MAX_EVENTS}"]
    return "\n".join(lines)


def _service_of(stream: str) -> str:
    name = stream.removeprefix(STREAM_PREFIX)
    return name.rsplit("-", 1)[0] if name[-1:].isdigit() else name


def parse_event(fields: dict[str, str]) -> dict[str, Any]:
    """One result row as {time, service, level, logger, message, details}. JSON log lines are
    unpacked; anything else (e.g. a library printing plain text) is shown as its message."""
    raw = fields.get("@message", "")
    data: dict[str, Any] = {}
    try:
        parsed = json.loads(raw)
        data = parsed if isinstance(parsed, dict) else {}
    except ValueError:
        data = {}
    message = str(data.get("message", raw if not data else ""))
    plain_level = None
    if not data:
        m = _PLAIN_LEVEL.match(raw)
        if m:
            plain_level, message = m.group(1), raw[m.end() :]
    details = {
        k: v for k, v in data.items() if k not in {"time", "level", "service", "logger", "message"}
    }
    return {
        "time": fields.get("@timestamp", ""),
        "service": str(data.get("service") or _service_of(fields.get("@logStream", ""))),
        "level": str(data.get("level") or fields.get("level") or plain_level or "").upper() or None,
        "logger": data.get("logger"),
        "message": message[:MAX_MESSAGE_CHARS],
        "details": details or None,
    }


def _run(client: Any, group: str, q: LogQuery, now: float) -> list[dict[str, Any]]:
    start = int(now - WINDOW_MINUTES[q.window] * 60)
    query_id = client.start_query(
        logGroupName=group,
        startTime=start,
        endTime=int(now),
        queryString=build_query(q),
        limit=MAX_EVENTS,
    )["queryId"]
    deadline = time.monotonic() + TIMEOUT_S
    while True:
        result = client.get_query_results(queryId=query_id)
        if result["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            break
        if time.monotonic() > deadline:
            client.stop_query(queryId=query_id)
            raise LogsUnavailableError("the log search took too long; try a shorter period")
        time.sleep(POLL_S)
    if result["status"] != "Complete":
        raise LogsUnavailableError(f"the log search {result['status'].lower()}")
    return [parse_event({f["field"]: f["value"] for f in row}) for row in result.get("results", [])]


async def recent(
    group: str, region: str, q: LogQuery, client: Any | None = None
) -> list[dict[str, Any]]:
    """Newest log lines first. `client` is a boto3 CloudWatch Logs client (tests pass a fake)."""
    logs = client or boto3.client("logs", region_name=region or "us-east-1")
    try:
        return await asyncio.to_thread(_run, logs, group, q, time.time())
    except LogsUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001 - AWS errors become one message for the panel
        raise LogsUnavailableError("CloudWatch could not be reached") from exc
