from dataclasses import dataclass
from datetime import datetime
from typing import Any

PARQUET_MIME = "application/vnd.apache.parquet"
MAX_SHEETS = 5


class DatasetError(Exception):
    """A file that can't become a dataset. `user_message` is safe to show."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


@dataclass(frozen=True)
class Limits:
    max_rows: int = 2_000_000
    max_columns: int = 200


@dataclass(frozen=True)
class Converted:
    """One table ready to store: a CSV file, or one sheet of a workbook."""

    sheet: str
    parquet: bytes
    columns: tuple[dict[str, str], ...]  # [{name, type}] with DuckDB type names
    column_map: dict[str, str]  # safe name -> original header
    row_count: int


@dataclass(frozen=True)
class Dataset:
    id: str
    owner_id: str
    origin: str
    title: str
    filename: str
    sheet: str
    s3_key_original: str
    s3_key: str
    status: str
    error: str | None
    columns: tuple[dict[str, str], ...]
    column_map: dict[str, str]
    row_count: int
    size_bytes: int
    sha256: str
    profile: dict[str, Any]
    summary: str
    created_at: datetime | None


def dataset_key(owner_id: str, dataset_id: str) -> str:
    return f"datasets/{owner_id}/{dataset_id}/data.parquet"


def original_key(owner_id: str, dataset_id: str, ext: str) -> str:
    """Never derived from the user's filename."""
    return f"datasets/{owner_id}/{dataset_id}/original{ext}"
