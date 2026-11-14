"""Local-development defaults must never reach a deployed environment."""

import pytest
from eagleeye_core.config import LOCAL_S3_SECRET, Settings
from pydantic import ValidationError


def test_local_defaults_are_fine_locally() -> None:
    s = Settings(_env_file=None, app_env="local")
    assert s.s3_secret_key == LOCAL_S3_SECRET


@pytest.mark.parametrize("env", ["staging", "production"])
def test_deployed_envs_refuse_the_local_storage_secret(env: str) -> None:
    with pytest.raises(ValidationError, match="S3_SECRET_KEY"):
        Settings(_env_file=None, app_env=env)


def test_deployed_env_with_real_storage_keys_loads() -> None:
    s = Settings(
        _env_file=None,
        app_env="production",
        s3_access_key="prod-key",
        s3_secret_key="a-real-secret",  # noqa: S106 — test value
    )
    assert s.app_env == "production"


def test_pool_sizes_are_settings_with_safe_defaults() -> None:
    s = Settings(_env_file=None)
    assert (s.db_pool_max_api, s.db_pool_max_worker, s.db_pool_max_gateway) == (10, 10, 5)
    small = Settings(_env_file=None, db_pool_max_api=3, db_pool_max_worker=2, db_pool_max_gateway=2)
    assert (small.db_pool_max_api, small.db_pool_max_worker, small.db_pool_max_gateway) == (3, 2, 2)


def test_qdrant_api_key_defaults_to_none_for_the_local_server() -> None:
    assert Settings(_env_file=None).qdrant_api_key == ""
