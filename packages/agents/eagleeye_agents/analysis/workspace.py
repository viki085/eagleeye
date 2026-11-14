"""DataWorkspace: everything the analysis and chart tools may touch, scoped to one user.

Inputs are resolved by id IN CODE with an ownership check (uploaded data files in the
documents bucket, result tables in the artifacts bucket); the model can name an id but
never reach another user's data.
"""

import io
import uuid
from typing import Any, Protocol

import asyncpg
import pyarrow.parquet as pq
from eagleeye_core.pii import pii_column_name
from eagleeye_core.storage import ObjectNotFoundError, ObjectStore
from eagleeye_datasets.artifacts import save_notebook_artifact, save_table_artifact
from eagleeye_datasets.models import Dataset
from eagleeye_datasets.repo import DatasetRepo

from eagleeye_agents.analysis.types import LoadedInput


class DataWorkspace(Protocol):
    async def list_datasets(self, user_id: str) -> list[Dataset]: ...

    async def load(self, user_id: str, ref_id: str) -> LoadedInput | None: ...

    async def save_result(
        self,
        *,
        user_id: str,
        run_id: str,
        title: str,
        parquet: bytes,
        columns: list[dict[str, str]],
        row_count: int,
        truncated: bool,
        source_refs: dict[str, Any],
    ) -> str: ...

    async def save_notebook(
        self,
        *,
        notebook_id: str,
        user_id: str,
        run_id: str,
        title: str,
        manifest: dict[str, Any],
        figures: list[tuple[str, bytes]],
    ) -> str: ...

    async def sandbox_runs_last_hour(self, user_id: str) -> int: ...

    async def log_sandbox_run(
        self,
        *,
        run_id: str,
        user_id: str,
        mode: str,
        code: str,
        status: str,
        duration_ms: int,
        error: str | None,
    ) -> None: ...


def _uuid(value: str) -> str | None:
    try:
        return str(uuid.UUID(value.strip()))
    except (ValueError, AttributeError):
        return None


def pii_names(columns: tuple[dict[str, str], ...], profile: dict[str, Any]) -> frozenset[str]:
    flagged = {c["name"].lower() for c in profile.get("columns", []) if "pii" in c.get("flags", [])}
    named = {c["name"].lower() for c in columns if pii_column_name(c["name"])}
    return frozenset(flagged | named)


class PgDataWorkspace:
    def __init__(self, pool: asyncpg.Pool, data_store: ObjectStore, artifact_store: ObjectStore):
        self._pool = pool
        self._repo = DatasetRepo(pool)
        self._data_store = data_store
        self._artifact_store = artifact_store

    async def list_datasets(self, user_id: str) -> list[Dataset]:
        return await self._repo.list_for(user_id, ready_only=True)

    async def load(self, user_id: str, ref_id: str) -> LoadedInput | None:
        key = _uuid(ref_id)
        if key is None:
            return None
        ds = await self._repo.get(key, user_id)
        if ds is not None:
            if ds.status != "READY" or not ds.s3_key:
                return None
            data = await self._get(self._data_store, ds.s3_key)
            if data is None:
                return None
            return LoadedInput(
                ds.id,
                "dataset",
                ds.title,
                data,
                ds.columns,
                ds.row_count,
                pii_names(ds.columns, ds.profile),
                ds.profile,
            )
        row = await self._repo.table_artifact(key, user_id)
        if row is None:
            return None
        data = await self._get(self._artifact_store, row["s3_key"])
        if data is None:
            return None
        columns = tuple(
            {"name": f.name, "type": str(f.type)} for f in pq.read_schema(io.BytesIO(data))
        )
        return LoadedInput(
            str(row["id"]),
            "result",
            row["title"],
            data,
            columns,
            row["row_count"],
            pii_names(columns, {}),
        )

    @staticmethod
    async def _get(store: ObjectStore, key: str) -> bytes | None:
        try:
            return await store.get(key)
        except ObjectNotFoundError:
            return None

    async def save_result(self, **kw: Any) -> str:
        return await save_table_artifact(self._artifact_store, self._pool, **kw)

    async def save_notebook(self, **kw: Any) -> str:
        return await save_notebook_artifact(self._artifact_store, self._pool, **kw)

    async def sandbox_runs_last_hour(self, user_id: str) -> int:
        return await self._repo.sandbox_runs_last_hour(user_id)

    async def log_sandbox_run(self, **kw: Any) -> None:
        await self._repo.log_sandbox_run(**kw)
