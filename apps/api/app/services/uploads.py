"""Upload boundary helpers: never trust the client's filename, MIME or size."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from fastapi import UploadFile

from app.errors import ApiException

READ_CHUNK_BYTES = 1024 * 1024
MAX_FILENAME_CHARS = 200
MAX_TITLE_CHARS = 120

# Extension → stored MIME. The worker re-checks content against the extension.
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}

_UNSAFE_CHARS = re.compile(r"[\x00-\x1f\x7f<>:\"|?*]")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class UploadedBytes:
    data: bytes
    sha256: str


def safe_filename(raw: str | None) -> str:
    name = unicodedata.normalize("NFC", raw or "")
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE_CHARS.sub("", name).strip().strip(".")
    return name[-MAX_FILENAME_CHARS:] or "upload"


def extension_of(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def title_from(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    title = _SPACES.sub(" ", stem.replace("_", " ")).strip()
    return title[:MAX_TITLE_CHARS] or "Untitled document"


def require_supported(filename: str) -> tuple[str, str]:
    ext = extension_of(filename)
    mime = ALLOWED_EXTENSIONS.get(ext)
    if mime is None:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ApiException(
            415, "UNSUPPORTED_MEDIA_TYPE", f"Unsupported file type. Allowed: {allowed}"
        )
    return ext, mime


async def read_limited(file: UploadFile, max_bytes: int) -> UploadedBytes:
    digest = hashlib.sha256()
    parts: list[bytes] = []
    size = 0
    while chunk := await file.read(READ_CHUNK_BYTES):
        size += len(chunk)
        if size > max_bytes:
            limit_mb = max_bytes // (1024 * 1024)
            raise ApiException(413, "PAYLOAD_TOO_LARGE", f"File exceeds the {limit_mb} MB limit.")
        digest.update(chunk)
        parts.append(chunk)
    if size == 0:
        raise ApiException(400, "BAD_REQUEST", "The file is empty.")
    return UploadedBytes(b"".join(parts), digest.hexdigest())


def object_key(scope: str, doc_id: str, ext: str) -> str:
    """Never derived from the user's filename."""
    return f"{scope}/{doc_id}/original{ext}"
