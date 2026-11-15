"""Logging for every service: readable text on a laptop, one JSON object per line in the cloud
(CloudWatch searches the fields). Closes the "structured logs" item deferred in C9."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# extra attributes worth a field of their own when a log call passes them
CONTEXT_FIELDS = ("request_id", "run_id", "chat_id", "user_id", "task_id")
TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value not in (None, "", "-"):
                data[field] = str(value)
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


class _DefaultRequestId(logging.Filter):
    """Text format needs %(request_id)s on every record, including those outside a request."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


def configure_logging(
    settings: Any, service: str, filters: list[logging.Filter] | None = None
) -> None:
    """Replaces the root handlers: JSON when settings.log_format == "json", else text."""
    handler = logging.StreamHandler(sys.stderr)
    if str(settings.log_format).lower() == "json":
        handler.setFormatter(JsonFormatter(service))
    else:
        handler.setFormatter(logging.Formatter(TEXT_FORMAT))
    handler.addFilter(_DefaultRequestId())
    for f in filters or []:
        handler.addFilter(f)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(str(settings.log_level).upper())
    for noisy in ("httpx", "httpcore", "botocore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
