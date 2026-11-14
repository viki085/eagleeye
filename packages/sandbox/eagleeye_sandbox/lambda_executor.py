"""AnalysisExecutor backed by AWS Lambda (Phase 7A; C10 §2.4). Cloud counterpart of
DockerExecutor: same SandboxTask in, same SandboxResult out, same runner inside.

Data never travels in the invocation payload. Inputs are uploaded to a per-job prefix in the
transfer bucket and passed as single-use pre-signed GET links; the function uploads its
outputs through a pre-signed POST limited to `<prefix>out/` and a maximum size. The job's
objects are deleted afterwards, whatever happened. The invocation is never retried: running
untrusted code twice is not a safe default.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from botocore.exceptions import ClientError

from eagleeye_sandbox.result_io import MAX_OUTPUT_BYTES, parse_result, task_spec
from eagleeye_sandbox.types import SandboxResult, SandboxTask

logger = logging.getLogger(__name__)

LINK_TTL_S = 600
PING_CACHE_S = 30.0
UNAVAILABLE = "The analysis sandbox could not run this task."
CRASHED = "The analysis process stopped unexpectedly; try a smaller or simpler analysis."


class LambdaExecutor:
    def __init__(
        self,
        *,
        lambda_client: Any,
        s3_client: Any,
        presign_client: Any,
        bucket: str,
        function: str,
        mem_mb: int = 1024,
        timeout_s: int = 60,
        prefix: str = "sandbox",
    ) -> None:
        self._lambda = lambda_client
        self._s3 = s3_client
        self._presign = presign_client  # signs links with the address the function can reach
        self._bucket = bucket
        self._function = function
        self._mem_mb = mem_mb
        self._timeout_s = timeout_s
        self._prefix = prefix.strip("/")
        self._ping: tuple[float, bool] | None = None

    async def available(self) -> bool:
        if self._ping and time.monotonic() - self._ping[0] < PING_CACHE_S:
            return self._ping[1]
        ok = await asyncio.to_thread(self._ping_sync)
        self._ping = (time.monotonic(), ok)
        return ok

    def _ping_sync(self) -> bool:
        try:
            resp = self._lambda.invoke(
                FunctionName=self._function,
                InvocationType="RequestResponse",
                Payload=json.dumps({"ping": True}),
            )
            return json.loads(resp["Payload"].read() or b"{}").get("pong") is True
        except Exception:  # noqa: BLE001 - any failure means "not available"
            logger.warning("sandbox function %s not reachable", self._function, exc_info=True)
            return False

    async def run(self, task: SandboxTask) -> SandboxResult:
        return await asyncio.to_thread(self._run_sync, task)

    def _event(self, task: SandboxTask, prefix: str) -> dict[str, Any]:
        inputs = []
        for item in task.inputs:
            key = f"{prefix}in/{item.name}.parquet"
            self._s3.put_object(Bucket=self._bucket, Key=key, Body=item.parquet)
            url = self._presign.generate_presigned_url(
                "get_object", Params={"Bucket": self._bucket, "Key": key}, ExpiresIn=LINK_TTL_S
            )
            inputs.append({"name": item.name, "file": f"{item.name}.parquet", "url": url})
        out = f"{prefix}out/"
        post = self._presign.generate_presigned_post(
            Bucket=self._bucket,
            Key=f"{out}${{filename}}",
            Conditions=[
                ["starts-with", "$key", out],
                ["content-length-range", 0, MAX_OUTPUT_BYTES],
            ],
            ExpiresIn=LINK_TTL_S,
        )
        return {
            "task": task_spec(task, []),
            "inputs": inputs,
            "upload": {"url": post["url"], "fields": post["fields"], "prefix": out},
            "timeout_s": self._timeout_s,
            "mem_mb": self._mem_mb,
        }

    def _run_sync(self, task: SandboxTask) -> SandboxResult:
        started = time.monotonic()
        prefix = f"{self._prefix}/{uuid.uuid4().hex}/"
        try:
            event = self._event(task, prefix)
            resp = self._lambda.invoke(
                FunctionName=self._function,
                InvocationType="RequestResponse",
                Payload=json.dumps(event),
            )
            raw = resp["Payload"].read()
            if resp.get("FunctionError"):
                logger.error("sandbox function error: %s", raw[:800])
                return SandboxResult("unavailable", error=UNAVAILABLE, duration_ms=_ms(started))
            body = json.loads(raw or b"{}")
            return self._result(body.get("result") or {}, prefix, _ms(started))
        except Exception:  # noqa: BLE001 - transport / AWS failures become "unavailable"
            logger.exception("sandbox invocation failed")
            return SandboxResult("unavailable", error=UNAVAILABLE, duration_ms=_ms(started))
        finally:
            self._cleanup(prefix)

    def _result(self, body: dict, prefix: str, duration_ms: int) -> SandboxResult:
        status = body.get("status")
        if status == "timeout":
            return SandboxResult(
                "timeout",
                error=f"The analysis took longer than {self._timeout_s}s and was stopped.",
                duration_ms=duration_ms,
            )
        if status == "crashed":
            return SandboxResult("error", error=CRASHED, duration_ms=duration_ms)
        if status == "error" and body.get("error_type") == "MemoryError":
            return SandboxResult(
                "oom",
                error=f"The analysis ran out of memory ({self._mem_mb} MB).",
                duration_ms=duration_ms,
            )

        def read(name: str) -> bytes | None:
            if not name:
                return None
            try:
                obj = self._s3.get_object(Bucket=self._bucket, Key=f"{prefix}out/{name}")
            except ClientError:
                return None
            return obj["Body"].read(MAX_OUTPUT_BYTES + 1)

        return parse_result(body, read, duration_ms)

    def _cleanup(self, prefix: str) -> None:
        try:
            listed = self._s3.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
            keys = [{"Key": o["Key"]} for o in listed.get("Contents", [])]
            if keys:
                self._s3.delete_objects(Bucket=self._bucket, Delete={"Objects": keys})
        except Exception:  # noqa: BLE001 - leftovers expire through the bucket's lifecycle rule
            logger.warning("sandbox transfer cleanup failed for %s", prefix, exc_info=True)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def build_lambda_executor(settings: Any, mem_mb: int, timeout_s: int) -> LambdaExecutor:
    """From settings: the function (or a local emulator endpoint) and the transfer bucket."""
    import boto3
    from botocore.config import Config

    region = settings.aws_region
    emulator = settings.sandbox_lambda_endpoint_url
    # the local emulator ignores request signing but boto3 still wants credentials to sign
    # with; on AWS the machine's or task's role is used (default credential chain)
    emulator_keys = (
        {"aws_access_key_id": "local-emulator", "aws_secret_access_key": "local-emulator"}  # noqa: S106
        if emulator
        else {}
    )
    lambda_client = boto3.client(
        "lambda",
        region_name=region,
        endpoint_url=emulator or None,
        **emulator_keys,
        config=Config(read_timeout=timeout_s + 30, connect_timeout=10, retries={"max_attempts": 0}),
    )
    keys = {
        "aws_access_key_id": settings.s3_access_key or None,
        "aws_secret_access_key": settings.s3_secret_key or None,
    }
    custom = bool(settings.s3_endpoint_url)
    s3_config = Config(s3={"addressing_style": "path"} if custom else {}, signature_version="s3v4")

    def s3(endpoint: str) -> Any:
        return boto3.client(
            "s3", region_name=region, endpoint_url=endpoint or None, config=s3_config, **keys
        )

    transfer_endpoint = settings.sandbox_transfer_endpoint_url or settings.s3_endpoint_url
    return LambdaExecutor(
        lambda_client=lambda_client,
        s3_client=s3(settings.s3_endpoint_url),
        presign_client=s3(transfer_endpoint),
        bucket=settings.sandbox_transfer_bucket or settings.artifacts_bucket,
        function=settings.sandbox_lambda_function,
        mem_mb=mem_mb,
        timeout_s=timeout_s,
    )
