"""Picks the analysis sandbox from settings: Docker on a laptop, Lambda in the cloud."""

from typing import Any

from eagleeye_sandbox.docker_executor import DockerExecutor
from eagleeye_sandbox.types import AnalysisExecutor

BACKENDS = ("docker", "lambda")


def build_executor(settings: Any, mem_mb: int, timeout_s: int) -> AnalysisExecutor:
    backend = str(settings.sandbox_backend).strip().lower()
    if backend == "lambda":
        from eagleeye_sandbox.lambda_executor import build_lambda_executor

        return build_lambda_executor(settings, mem_mb, timeout_s)
    if backend == "docker":
        return DockerExecutor(settings.sandbox_image, mem_mb, timeout_s)
    raise ValueError(f"SANDBOX_BACKEND must be one of {', '.join(BACKENDS)}, not '{backend}'")
