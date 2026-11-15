from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiError(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class PageMeta(BaseModel):
    page: int
    limit: int
    total: int


class Envelope(BaseModel, Generic[T]):  # noqa: UP046 - pydantic generic models need Generic
    """Consistent response envelope for all JSON endpoints (LLD §2.2)."""

    success: bool
    data: T | None = None
    error: ApiError | None = None
    meta: PageMeta | None = None


def ok(data: Any, meta: PageMeta | None = None) -> dict:
    return Envelope(success=True, data=data, meta=meta).model_dump()


def fail(code: str, message: str, request_id: str | None = None) -> dict:
    return Envelope(
        success=False, error=ApiError(code=code, message=message, request_id=request_id)
    ).model_dump()
