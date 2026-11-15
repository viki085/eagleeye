"""JSON log lines for CloudWatch; the laptop keeps readable text."""

import json
import logging

from eagleeye_core.config import Settings
from eagleeye_core.logs import JsonFormatter, configure_logging


def record(msg: str = "hello %s", args: tuple = ("world",), **extra: object) -> logging.LogRecord:
    rec = logging.LogRecord("app.test", logging.WARNING, __file__, 10, msg, args, None)
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_json_line_has_the_fields_cloudwatch_searches() -> None:
    line = JsonFormatter("api").format(record(request_id="abc123", run_id="r1"))
    data = json.loads(line)
    assert data["level"] == "WARNING" and data["logger"] == "app.test"
    assert data["message"] == "hello world" and data["service"] == "api"
    assert data["request_id"] == "abc123" and data["run_id"] == "r1"
    assert data["time"].endswith("Z") and "\n" not in line


def test_missing_request_id_is_left_out_and_exceptions_are_included() -> None:
    try:
        raise ValueError("bad input")
    except ValueError:
        import sys

        rec = record("failed", ())
        rec.exc_info = sys.exc_info()
    data = json.loads(JsonFormatter("worker").format(rec))
    assert "request_id" not in data
    assert "ValueError: bad input" in data["exception"]


def test_request_id_placeholder_is_not_logged() -> None:
    data = json.loads(JsonFormatter("api").format(record(request_id="-")))
    assert "request_id" not in data


def test_configure_logging_picks_the_format() -> None:
    configure_logging(Settings(_env_file=None, log_format="json"), "api")
    assert isinstance(logging.getLogger().handlers[0].formatter, JsonFormatter)
    configure_logging(Settings(_env_file=None, log_format="text"), "api")
    assert not isinstance(logging.getLogger().handlers[0].formatter, JsonFormatter)
