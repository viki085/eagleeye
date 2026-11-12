"""SCANNING stage: decide the real file type from extension AND content.

The client-supplied MIME is never trusted; the extension must agree with the bytes.
"""

import io
import zipfile
from typing import Literal

from ingest_worker.errors import PermanentIngestError

FileKind = Literal["pdf", "docx", "markdown", "text"]

SUPPORTED_EXTENSIONS: dict[str, FileKind] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
}


def _is_docx(data: bytes) -> bool:
    if not data.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return "word/document.xml" in zf.namelist()
    except zipfile.BadZipFile:
        return False


def _is_utf8_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def sniff(filename: str, data: bytes) -> FileKind:
    if not data:
        raise PermanentIngestError("The file is empty.")
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    kind = SUPPORTED_EXTENSIONS.get(ext)
    if kind is None:
        raise PermanentIngestError(f"Unsupported file type '{ext or 'none'}'.")

    matches = {
        "pdf": data.startswith(b"%PDF-"),
        "docx": _is_docx(data),
        "markdown": _is_utf8_text(data),
        "text": _is_utf8_text(data),
    }[kind]
    if not matches:
        raise PermanentIngestError(
            f"The file content does not match its '{ext}' extension."
        )
    return kind
