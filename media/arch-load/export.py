"""Export a load run's numbers into one timeline for the video (Part 2 and Part 1's scaling scene).

Reads, for the window of the run recorded in raw/<profile>/k6.json:
  - k6's per-answer lines from CloudWatch Logs ("ANS <epoch ms> <kind> <seconds> <ok>") and its
    end-of-run summary ("K6_SUMMARY {...}")
  - CloudWatch metrics: running tasks per service (Container Insights), answers in progress
    (EagleEye/LoadTest ActiveAnswers), load balancer requests
and writes raw/<profile>/timeline.json: one row per minute (users, answers, average and p95
response time, error rate, tasks per service) plus the clips' start offsets.

    uv run --with boto3 python media/arch-load/export.py --profile rehearsal|run
"""

import argparse
import json
import math
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3

HERE = Path(__file__).parent
REGION = "us-east-1"
CLUSTER = "eagleeye-lt"
LOG_GROUP = "/eagleeye/loadtest"
SERVICES = ["api", "agent-worker", "gateway", "ingest-worker"]
KINDS = ("docs", "sql", "chart", "attack", "notebook")
ANS = re.compile(r"ANS (\d+) (\w+) ([\d.]+) ([01])")
# k6 stages per profile (as evals/load/chat.js): (seconds, target users)
STAGES = {
    "rehearsal": [(60, 20), (60, 100), (420, 100), (60, 0)],
    "run": [
        (20, 1),
        (100, 1),
        (40, 50),
        (160, 50),
        (60, 500),
        (180, 500),
        (60, 1000),
        (180, 1000),
        (120, 2000),
        (300, 2000),
        (180, 0),
    ],
}


def users_at(profile: str, t: float) -> int:
    """Target users t seconds into the run (k6 ramps linearly within a stage)."""
    start, prev = 0.0, 0
    for seconds, target in STAGES[profile]:
        if t <= start + seconds:
            return round(prev + (target - prev) * (t - start) / seconds)
        start, prev = start + seconds, target
    return 0


def p95(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, math.ceil(0.95 * len(s)) - 1)]


def k6_lines(logs, start_ms: int, end_ms: int) -> tuple[list[tuple], dict | None]:
    answers, summary = [], None
    kwargs = {
        "logGroupName": LOG_GROUP,
        "logStreamNamePrefix": "k6/",
        "startTime": start_ms,
        "endTime": end_ms,
    }
    for page in logs.get_paginator("filter_log_events").paginate(**kwargs):
        for e in page["events"]:
            msg = e["message"]
            if m := ANS.search(msg):
                answers.append((int(m[1]), m[2], float(m[3]), m[4] == "1"))
            elif "K6_SUMMARY " in msg:
                summary = json.loads(msg.split("K6_SUMMARY ", 1)[1])
    return answers, summary


def metric_series(cw, start: datetime, end: datetime) -> dict[str, dict[int, float]]:
    queries = [
        {
            "Id": f"t{i}",
            "Label": s,
            "MetricStat": {
                "Metric": {
                    "Namespace": "ECS/ContainerInsights",
                    "MetricName": "RunningTaskCount",
                    "Dimensions": [
                        {"Name": "ClusterName", "Value": CLUSTER},
                        {"Name": "ServiceName", "Value": s},
                    ],
                },
                "Period": 60,
                "Stat": "Average",
            },
        }
        for i, s in enumerate(SERVICES)
    ]
    queries.append(
        {
            "Id": "active",
            "Label": "active_answers",
            "MetricStat": {
                "Metric": {"Namespace": "EagleEye/LoadTest", "MetricName": "ActiveAnswers"},
                "Period": 60,
                "Stat": "Average",
            },
        }
    )
    out: dict[str, dict[int, float]] = {}
    resp = cw.get_metric_data(MetricDataQueries=queries, StartTime=start, EndTime=end)
    for r in resp["MetricDataResults"]:
        out[r["Label"]] = {
            int(ts.timestamp()): v for ts, v in zip(r["Timestamps"], r["Values"], strict=True)
        }
    return out


def build(profile: str) -> dict:
    raw = HERE / "raw" / profile
    run = json.loads((raw / "k6.json").read_text())
    t0 = run["t0"]
    total = sum(s for s, _ in STAGES[profile]) + 120  # + graceful ramp-down
    session = boto3.Session(profile_name="eagleeye", region_name=REGION)
    answers, summary = k6_lines(session.client("logs"), t0 - 60_000, t0 + total * 1000)
    start = datetime.fromtimestamp(t0 / 1000, UTC).replace(second=0, microsecond=0)
    series = metric_series(session.client("cloudwatch"), start, start + timedelta(seconds=total))

    minutes = []
    for i in range(math.ceil(total / 60)):
        lo, hi = t0 + i * 60_000, t0 + (i + 1) * 60_000
        rows = [a for a in answers if lo <= a[0] < hi]
        secs = [a[2] for a in rows if a[3]]
        bucket = int((start + timedelta(minutes=i)).timestamp())
        minutes.append(
            {
                "minute": i,
                "users": users_at(profile, i * 60 + 30),
                "answers": len(rows),
                "avg_s": round(sum(secs) / len(secs), 2) if secs else None,
                "p95_s": p95(secs),
                "error_rate": round(sum(not a[3] for a in rows) / len(rows), 4) if rows else 0,
                "kinds": {
                    k: sum(a[1] == k for a in rows)
                    for k in ("docs", "sql", "chart", "attack", "notebook")
                },
                "tasks": {s: series.get(s, {}).get(bucket) for s in SERVICES},
                "active_answers": series.get("active_answers", {}).get(bucket),
            }
        )
    clips = []
    for meta in sorted(raw.glob("*.json")):
        if meta.name in ("k6.json", "timeline.json"):
            continue
        d = json.loads(meta.read_text())
        clips.append(
            {
                "name": meta.stem,
                "offset_s": round((d["startedAtEpoch"] - t0) / 1000, 1),
                "seconds": d.get("seconds"),
                "users": users_at(profile, (d["startedAtEpoch"] - t0) / 1000),
                "answer_s": d.get("answerSeconds"),
                "kind": d.get("kind"),
            }
        )
    ok = [a[2] for a in answers if a[3]]
    return {
        "profile": profile,
        "t0": t0,
        "totals": {
            "answers": len(answers),
            "errors": sum(not a[3] for a in answers),
            "avg_s": round(sum(ok) / len(ok), 2) if ok else None,
            "p95_s": p95(ok),
            "peak_tasks": {s: max((m["tasks"][s] or 0) for m in minutes) for s in SERVICES},
        },
        "minutes": minutes,
        "clips": clips,
        "k6_summary_present": summary is not None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--profile", default="rehearsal", choices=sorted(STAGES))
    args = parser.parse_args()
    timeline = build(args.profile)
    out = HERE / "raw" / args.profile / "timeline.json"
    out.write_text(json.dumps(timeline, indent=2))
    print(f"wrote {out}: {timeline['totals']}")


if __name__ == "__main__":
    main()
