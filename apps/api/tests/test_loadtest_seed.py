"""scripts/loadtest_seed.py: tokens the API accepts, and the refusal outside APP_ENV=loadtest."""

import importlib.util
import json
from pathlib import Path

import pytest
from app import auth

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "loadtest_seed", ROOT / "scripts" / "loadtest_seed.py"
)
seed = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(seed)  # type: ignore[union-attr]


def test_keys_and_tokens_verify_with_the_api(tmp_path: Path) -> None:
    seed.make_keys(tmp_path)
    seed.write_tokens(tmp_path, count=40, hours=2)
    tokens = json.loads((tmp_path / "tokens.json").read_text())
    public = (tmp_path / "public.pem").read_text()
    verifier = auth.LoadTestVerifier(public, None)  # type: ignore[arg-type]
    assert verifier.verify(tokens["users"][0]["token"])["sub"] == "loadtest:1"
    assert verifier.verify(tokens["admin"])["sub"] == seed.ADMIN_SUBJECT
    assert [u["n"] for u in tokens["users"] if u["analysis"]] == [20, 40]  # 5% of users


def test_token_lifetime_is_capped(tmp_path: Path) -> None:
    seed.make_keys(tmp_path)
    with pytest.raises(SystemExit):
        seed.write_tokens(tmp_path, count=1, hours=7)


def test_refuses_outside_loadtest(monkeypatch: pytest.MonkeyPatch) -> None:
    from eagleeye_core.config import get_settings

    monkeypatch.setenv("APP_ENV", "local")
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit, match="refusing"):
            seed._refuse_unless_loadtest()
    finally:
        get_settings.cache_clear()


def test_sample_csv_has_a_header_and_48_rows() -> None:
    lines = seed.sample_csv(20).decode().splitlines()
    assert lines[0] == "month,region,orders,revenue" and len(lines) == 49


def test_writing_users_needs_the_database_host_confirmed() -> None:
    url = "postgresql://u:p@db.loadtest.example:5432/postgres"
    assert seed.db_host(url) == "db.loadtest.example"
    seed._refuse_unless_confirmed(url, "db.loadtest.example")  # matches: allowed
    for wrong in ("", "db.prod.example", "loadtest"):
        with pytest.raises(SystemExit, match="refusing"):
            seed._refuse_unless_confirmed(url, wrong)


def test_key_and_tokens_are_owner_only(tmp_path: Path) -> None:
    import os
    import stat

    seed.make_keys(tmp_path / "keys")
    seed.write_tokens(tmp_path / "keys", count=1, hours=1)
    if os.name == "posix":  # Windows has no POSIX modes; NTFS ACLs apply there
        for name in ("private.pem", "tokens.json"):
            mode = stat.S_IMODE((tmp_path / "keys" / name).stat().st_mode)
            assert mode == 0o600
