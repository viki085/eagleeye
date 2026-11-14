"""Container health check for the Python services (stdlib only, no shell).

api / gateway: their liveness endpoint answers 200. Workers: the Celery process is running
(PID 1 is celery); broker problems are reported by the API's status page, not by restarting.
"""

import os
import sys
import urllib.request

URLS = {
    "api": "http://127.0.0.1:8000/v1/health/live",
    "gateway": "http://127.0.0.1:8100/health",
}


def main() -> int:
    service = os.environ.get("SERVICE", "")
    url = URLS.get(service)
    if url is None:
        try:
            with open("/proc/1/cmdline", "rb") as f:
                return 0 if b"celery" in f.read() else 1
        except OSError:
            return 1
    try:
        with urllib.request.urlopen(url, timeout=4) as resp:  # noqa: S310 - fixed local URL
            return 0 if resp.status == 200 else 1
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
