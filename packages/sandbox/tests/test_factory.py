import pytest
from eagleeye_core.config import Settings
from eagleeye_sandbox.docker_executor import DockerExecutor
from eagleeye_sandbox.factory import build_executor
from eagleeye_sandbox.lambda_executor import LambdaExecutor


def test_docker_is_the_default() -> None:
    assert isinstance(build_executor(Settings(_env_file=None), 512, 30), DockerExecutor)


def test_lambda_backend() -> None:
    s = Settings(
        _env_file=None,
        sandbox_backend="lambda",
        sandbox_lambda_endpoint_url="http://localhost:9000",
    )
    executor = build_executor(s, 2048, 120)
    assert isinstance(executor, LambdaExecutor)
    assert executor._mem_mb == 2048 and executor._timeout_s == 120  # noqa: SLF001
    assert executor._bucket == s.artifacts_bucket  # noqa: SLF001 - default transfer bucket


def test_unknown_backend_fails_fast() -> None:
    with pytest.raises(ValueError, match="SANDBOX_BACKEND"):
        build_executor(Settings(_env_file=None, sandbox_backend="kubernetes"), 512, 30)
