"""LambdaExecutor with fake S3 / Lambda clients: transfer links, result mapping, cleanup."""

import io
import json

import pytest
from eagleeye_sandbox.lambda_executor import LambdaExecutor
from eagleeye_sandbox.types import SandboxInput, SandboxTask

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 16


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.presigned_get: list[tuple[str, int]] = []
        self.post: dict | None = None

    def put_object(self, Bucket, Key, Body, **kw):  # noqa: ANN001, ANN003, ANN201, N803
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):  # noqa: ANN001, ANN201, N803
        from botocore.exceptions import ClientError

        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}

    def list_objects_v2(self, Bucket, Prefix):  # noqa: ANN001, ANN201, N803
        return {"Contents": [{"Key": k} for k in self.objects if k.startswith(Prefix)]}

    def delete_objects(self, Bucket, Delete):  # noqa: ANN001, ANN201, N803
        for item in Delete["Objects"]:
            self.objects.pop(item["Key"], None)

    def generate_presigned_url(self, op, Params, ExpiresIn):  # noqa: ANN001, ANN201, N803
        self.presigned_get.append((Params["Key"], ExpiresIn))
        return f"https://s3.example/{Params['Key']}?sig=1"

    def generate_presigned_post(self, Bucket, Key, Conditions, ExpiresIn):  # noqa: ANN001, ANN201, N803
        self.post = {"Key": Key, "Conditions": Conditions, "ExpiresIn": ExpiresIn}
        return {"url": "https://s3.example/upload", "fields": {"policy": "p", "key": Key}}


class FakeLambda:
    """Plays the handler: writes the outputs it 'produced' into S3 under the upload prefix."""

    def __init__(
        self,
        s3: FakeS3,
        result: dict,
        files: dict[str, bytes] | None = None,
        function_error: str | None = None,
    ) -> None:
        self.s3, self.result, self.files = s3, result, files or {}
        self.function_error = function_error
        self.events: list[dict] = []

    def invoke(self, FunctionName, InvocationType, Payload):  # noqa: ANN001, ANN201, N803
        event = json.loads(Payload)
        self.events.append(event)
        if event.get("ping"):
            return {"StatusCode": 200, "Payload": io.BytesIO(b'{"pong": true}')}
        for name, data in self.files.items():
            self.s3.objects[event["upload"]["prefix"] + name] = data
        body = {"result": self.result, "uploaded": list(self.files)}
        resp = {"StatusCode": 200, "Payload": io.BytesIO(json.dumps(body).encode())}
        if self.function_error:
            resp["FunctionError"] = self.function_error
            resp["Payload"] = io.BytesIO(b'{"errorMessage": "Runtime exited"}')
        return resp


def task(mode: str = "python") -> SandboxTask:
    return SandboxTask(mode, "save_stat('n', 1)", (SandboxInput("ds_1", b"PAR1data"),))  # type: ignore[arg-type]


def executor(s3: FakeS3, lam: FakeLambda) -> LambdaExecutor:
    return LambdaExecutor(
        lambda_client=lam,
        s3_client=s3,
        presign_client=s3,
        bucket="b",
        function="eagleeye-sandbox",
        mem_mb=512,
        timeout_s=30,
    )


async def test_inputs_go_up_and_only_links_reach_the_function() -> None:
    s3 = FakeS3()
    lam = FakeLambda(s3, {"status": "ok", "tables": [], "stats": {"n": 1}})
    result = await executor(s3, lam).run(task())
    assert result.status == "ok" and result.stats == {"n": 1}
    (event,) = lam.events
    assert event["inputs"][0]["name"] == "ds_1" and event["inputs"][0]["url"].startswith("https://")
    assert "PAR1data" not in json.dumps(event)  # data never travels in the payload
    assert event["task"]["mode"] == "python" and event["timeout_s"] == 30 and event["mem_mb"] == 512
    assert all(expires <= 600 for _, expires in s3.presigned_get)


async def test_upload_form_is_limited_to_this_jobs_prefix_and_size() -> None:
    s3 = FakeS3()
    lam = FakeLambda(s3, {"status": "ok"})
    await executor(s3, lam).run(task())
    prefix = lam.events[0]["upload"]["prefix"]
    assert prefix.startswith("sandbox/") and prefix.endswith("/out/")
    conditions = s3.post["Conditions"]
    assert ["starts-with", "$key", prefix] in conditions
    assert any(c[0] == "content-length-range" for c in conditions if isinstance(c, list))


async def test_outputs_are_read_back_and_everything_is_deleted() -> None:
    s3 = FakeS3()
    body = {
        "status": "ok",
        "tables": [{"name": "t", "file": "t.parquet", "rows": 1, "columns": []}],
        "figures": [{"name": "fig_0_1", "file": "fig_0_1.png", "cell": 0}],
        "cells": [{"index": 0, "figures": ["fig_0_1"]}],
    }
    lam = FakeLambda(s3, body, {"t.parquet": b"PAR1table", "fig_0_1.png": PNG})
    result = await executor(s3, lam).run(task("notebook"))
    assert result.tables[0].parquet == b"PAR1table" and result.figures[0].png == PNG
    assert s3.objects == {}  # inputs and outputs removed


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"status": "timeout"}, "timeout"),
        ({"status": "error", "error": "MemoryError", "error_type": "MemoryError"}, "oom"),
        ({"status": "crashed"}, "error"),
        (
            {
                "status": "error",
                "error": "Cell 1: KeyError",
                "error_type": "KeyError",
                "cells": [{"index": 0}],
                "failed_cell": 1,
            },
            "error",
        ),
    ],
)
async def test_outcomes_map_like_the_docker_sandbox(body: dict, status: str) -> None:
    s3 = FakeS3()
    result = await executor(s3, FakeLambda(s3, body)).run(task())
    assert result.status == status
    if body.get("failed_cell") == 1:
        assert result.failed_cell == 1 and len(result.cells) == 1
    assert s3.objects == {}


async def test_function_error_is_unavailable_not_a_crash() -> None:
    s3 = FakeS3()
    lam = FakeLambda(s3, {}, function_error="Unhandled")
    result = await executor(s3, lam).run(task())
    assert result.status == "unavailable" and s3.objects == {}


async def test_available_pings_the_function() -> None:
    s3 = FakeS3()
    lam = FakeLambda(s3, {})
    assert await executor(s3, lam).available() is True
    assert lam.events == [{"ping": True}]


async def test_unreachable_function_is_not_available() -> None:
    class Down:
        def invoke(self, **kw):  # noqa: ANN003, ANN201
            raise OSError("connection refused")

    assert (
        await LambdaExecutor(
            lambda_client=Down(),
            s3_client=FakeS3(),
            presign_client=FakeS3(),
            bucket="b",
            function="f",
        ).available()
        is False
    )
