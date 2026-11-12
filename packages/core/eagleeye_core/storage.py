"""ObjectStore port + S3 adapter. Code speaks only the S3 protocol (ADR-26)."""

import asyncio
import logging
from typing import Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

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
    """boto3 is sync; every call is pushed to a thread so the event loop never blocks."""

    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket: str) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
        )

    async def ensure_bucket(self) -> None:
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
        except ClientError as exc:
            if not _is_not_found(exc):
                raise
            logger.info("creating bucket %s", self._bucket)
            await asyncio.to_thread(self._client.create_bucket, Bucket=self._bucket)

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
    return S3ObjectStore(s.s3_endpoint_url, s.s3_access_key, s.s3_secret_key, s.docs_bucket)
