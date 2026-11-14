"""The S3 adapter works against the local S3-compatible server and against real AWS S3 with
the machine's role (no keys in settings)."""

from eagleeye_core.config import Settings
from eagleeye_core.storage import S3ObjectStore


def _client_args(store: S3ObjectStore) -> dict:
    client = store._client  # noqa: SLF001 - inspecting the configured boto3 client
    creds = client._request_signer._credentials  # noqa: SLF001
    return {
        "endpoint": client.meta.endpoint_url,
        "region": client.meta.region_name,
        "addressing": client.meta.config.s3.get("addressing_style")
        if client.meta.config.s3
        else None,
        "access_key": creds.access_key if creds else None,
    }


def test_local_server_uses_its_endpoint_keys_and_path_addressing() -> None:
    s = Settings(_env_file=None, app_env="local")
    args = _client_args(S3ObjectStore.from_settings(s, s.docs_bucket))
    assert args["endpoint"] == "http://localhost:8333"
    assert args["addressing"] == "path"
    assert args["access_key"] == s.s3_access_key


def test_real_s3_uses_the_aws_endpoint_region_and_default_credentials(monkeypatch) -> None:  # noqa: ANN001
    # the machine's role reaches boto3 through the default chain; simulate it with env vars
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "role-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "role-secret")
    s = Settings(
        _env_file=None,
        app_env="production",
        s3_endpoint_url="",
        s3_access_key="",
        s3_secret_key="",
        aws_region="eu-west-1",
    )
    args = _client_args(S3ObjectStore.from_settings(s, "eagleeye-prod-docs"))
    assert args["endpoint"] == "https://s3.eu-west-1.amazonaws.com"
    assert args["region"] == "eu-west-1"
    assert args["addressing"] != "path"
    assert args["access_key"] == "role-key"  # from the default chain, not from settings


def test_deployed_env_may_rely_on_the_role_with_no_keys() -> None:
    s = Settings(_env_file=None, app_env="production", s3_access_key="", s3_secret_key="")
    assert s.s3_access_key == "" and s.aws_region == "us-east-1"
