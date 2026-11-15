"""ObjectStore port + S3 adapter. Code speaks only the S3 protocol (ADR-26)."""

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from eagleeye_core.config import Settings

logger = logging.getLogger(__name__)


class ObjectNotFoundError(Exception):
    pass


class ObjectStore(Protocol):
    async def ensure_bucket(self) -> None: ...

    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


def _is_not_found(exc: ClientError) -> bool:
    code = str(exc.response.get("Error", {}).get("Code", ""))
    return code in ("404", "NoSuchKey", "NoSuchBucket", "NotFound")


class S3ObjectStore:
    """boto3 is sync; every call is pushed to a thread so the event loop never blocks.

    With an endpoint (the local S3-compatible server) it uses path-style addressing and the given
    keys. Without one it talks to AWS S3 in `region`; empty keys mean boto3's default credential
    chain, i.e. the machine's or task's IAM role, so no keys live in settings.
    """

    def __init__(
        self,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
    ) -> None:
        self._bucket = bucket
        custom_endpoint = bool(endpoint_url)
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            region_name=region,
            config=Config(
                s3={"addressing_style": "path"} if custom_endpoint else {},
                retries={"max_attempts": 3},
            ),
        )

    @classmethod
    def from_settings(cls, settings: "Settings", bucket: str) -> "S3ObjectStore":
        return cls(
            settings.s3_endpoint_url,
            settings.s3_access_key,
            settings.s3_secret_key,
            bucket,
            settings.aws_region,
        )

    async def ensure_bucket(self) -> None:
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
        except ClientError as exc:
            if not _is_not_found(exc):
                raise
            logger.info("creating bucket %s", self._bucket)
            await asyncio.to_thread(self._client.create_bucket, Bucket=self._bucket)

    async def reachable(self) -> None:
        """Raises unless the bucket answers (for health checks; needs s3:ListBucket)."""
        await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    async def get(self, key: str) -> bytes:
        try:
            resp = await asyncio.to_thread(self._client.get_object, Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectNotFoundError(key) from exc
            raise
        return await asyncio.to_thread(resp["Body"].read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)


def build_object_store() -> S3ObjectStore:
    from eagleeye_core.config import get_settings

    s = get_settings()
    return S3ObjectStore.from_settings(s, s.docs_bucket)
