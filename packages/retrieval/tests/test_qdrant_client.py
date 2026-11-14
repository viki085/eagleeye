"""One place builds the Qdrant client: the local server has no key, Qdrant Cloud needs one."""

from eagleeye_core.config import Settings
from eagleeye_retrieval.stores.qdrant_store import build_qdrant_client


def test_local_qdrant_has_no_api_key() -> None:
    client = build_qdrant_client(Settings(_env_file=None))
    assert client._client._api_key is None  # noqa: SLF001


def test_qdrant_cloud_gets_the_api_key() -> None:
    s = Settings(
        _env_file=None, qdrant_url="https://xyz.cloud.qdrant.io:6333", qdrant_api_key="k-123"
    )
    client = build_qdrant_client(s)
    assert client._client._api_key == "k-123"  # noqa: SLF001
