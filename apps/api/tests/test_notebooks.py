"""Notebooks: owner-only manifest, figures and a valid .ipynb export."""

import base64
import json
import uuid

import pytest
from app.auth import AuthedUser, get_current_user
from app.main import create_app
from app.services.notebook_export import to_ipynb
from fastapi.testclient import TestClient

ME = AuthedUser(str(uuid.uuid4()), "user_me", "me@example.com", None, "member")
NB = str(uuid.uuid4())
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
MANIFEST = {
    "notebook_id": NB,
    "title": "Titanic EDA",
    "inputs": [{"name": "ds_1", "title": "titanic"}],
    "cells": [
        {
            "index": 0,
            "purpose": "Overview",
            "code": "df = datasets['ds_1']\nprint(df.shape)",
            "status": "ok",
            "stdout": "(891, 12)\n",
            "error": "",
            "note": "",
            "stats": {},
            "figures": [],
            "tables": [],
        },
        {
            "index": 1,
            "purpose": "Survival by sex",
            "code": "sns.barplot(...)",
            "status": "ok",
            "stdout": "",
            "error": "",
            "note": "",
            "stats": {"rate_female": 0.742},
            "figures": ["fig_1_1"],
            "tables": [
                {
                    "artifact_id": "a1",
                    "title": "by_sex",
                    "row_count": 2,
                    "columns": [
                        {"name": "sex", "type": "string"},
                        {"name": "rate", "type": "double"},
                    ],
                    "preview": [["female", 0.742], ["<b>male</b>", 0.189]],
                }
            ],
        },
        {
            "index": 2,
            "purpose": "Broken",
            "code": "1/0",
            "status": "error",
            "stdout": "",
            "error": "ZeroDivisionError: division by zero",
            "note": "",
            "stats": {},
            "figures": [],
            "tables": [],
        },
    ],
}


class FakePool:
    async def fetchrow(self, sql, notebook_id, user_id):  # noqa: ANN001, ANN201
        if user_id != ME.id or notebook_id != NB:
            return None
        return {
            "id": NB,
            "title": "Titanic EDA",
            "s3_key": f"artifacts/{ME.id}/notebooks/{NB}/notebook.json",
            "source_refs": {"figures": ["fig_1_1"]},
        }


class FakeStore:
    def __init__(self) -> None:
        self.objects = {
            f"artifacts/{ME.id}/notebooks/{NB}/notebook.json": json.dumps(MANIFEST).encode(),
            f"artifacts/{ME.id}/notebooks/{NB}/fig_1_1.png": PNG,
        }

    async def get(self, key):  # noqa: ANN001, ANN201
        from eagleeye_core.storage import ObjectNotFoundError

        if key not in self.objects:
            raise ObjectNotFoundError(key)
        return self.objects[key]


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: ME
    app.state.pool = FakePool()
    app.state.artifact_store = FakeStore()
    return TestClient(app)


def test_manifest_for_the_owner(client: TestClient) -> None:
    data = client.get(f"/v1/notebooks/{NB}").json()["data"]
    assert data["title"] == "Titanic EDA" and len(data["cells"]) == 3


def test_someone_elses_notebook_is_not_found(client: TestClient) -> None:
    other = AuthedUser(str(uuid.uuid4()), "user_x", "x@example.com", None, "member")
    client.app.dependency_overrides[get_current_user] = lambda: other
    assert client.get(f"/v1/notebooks/{NB}").status_code == 404
    assert client.get(f"/v1/notebooks/{NB}/figures/fig_1_1").status_code == 404
    assert client.get(f"/v1/notebooks/{NB}/notebook.ipynb").status_code == 404


def test_figure_is_served_as_png_with_safe_headers(client: TestClient) -> None:
    resp = client.get(f"/v1/notebooks/{NB}/figures/fig_1_1")
    assert resp.status_code == 200 and resp.content == PNG
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "private" in resp.headers["cache-control"]


@pytest.mark.parametrize("name", ["fig_9_9", "../notebook", "notebook.json", "fig_1_1.png"])
def test_unknown_or_unsafe_figure_names_are_refused(client: TestClient, name: str) -> None:
    assert client.get(f"/v1/notebooks/{NB}/figures/{name}").status_code == 404


def test_ipynb_download(client: TestClient) -> None:
    resp = client.get(f"/v1/notebooks/{NB}/notebook.ipynb")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.headers["content-disposition"].endswith('.ipynb"')
    nb = resp.json()
    assert nb["nbformat"] == 4 and nb["metadata"]["kernelspec"]["language"] == "python"


def test_ipynb_structure_outputs_and_no_html() -> None:
    nb = to_ipynb(MANIFEST, {"fig_1_1": PNG})
    kinds = [c["cell_type"] for c in nb["cells"]]
    # title + setup, then a heading and a code cell per notebook cell
    assert kinds[:2] == ["markdown", "code"] and kinds[2:] == ["markdown", "code"] * 3
    setup = "".join(nb["cells"][1]["source"])
    assert "titanic" in setup and "def save_table" in setup and "def save_stat" in setup
    overview = nb["cells"][3]
    assert "".join(overview["source"]).startswith("df = datasets")
    assert overview["outputs"][0] == {
        "output_type": "stream",
        "name": "stdout",
        "text": ["(891, 12)\n"],
    }
    survival = nb["cells"][5]["outputs"]
    images = [o for o in survival if "image/png" in o.get("data", {})]
    assert base64.b64decode(images[0]["data"]["image/png"]) == PNG
    text = json.dumps(nb)
    assert "text/html" not in text and "application/javascript" not in text  # no active content
    assert "rate_female = 0.742" in text and "<b>male</b>" in text  # plain text, not markup
    broken = nb["cells"][7]["outputs"]
    assert broken[0]["name"] == "stderr" and "ZeroDivisionError" in "".join(broken[0]["text"])
    for cell in nb["cells"]:
        assert set(cell) >= {"cell_type", "metadata", "source"}
        if cell["cell_type"] == "code":
            assert {"execution_count", "outputs"} <= set(cell)
