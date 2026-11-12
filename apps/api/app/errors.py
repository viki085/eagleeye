"""Every error leaves the API in the standard envelope (LLD §2.2)."""

import logging

from eagleeye_core.envelope import fail
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    502: "UPSTREAM_ERROR",
}


class ApiException(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Invalid request."
    first = errors[0]
    where = ".".join(str(p) for p in first.get("loc", ()) if p not in ("body", "query", "path"))
    return f"{where}: {first.get('msg', 'invalid')}" if where else str(first.get("msg"))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiException)
    async def _api(_req: Request, exc: ApiException) -> JSONResponse:
        return JSONResponse(fail(exc.code, exc.message), status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(
            fail(code, str(exc.detail)), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(fail("VALIDATION_ERROR", _validation_message(exc)), status_code=422)
