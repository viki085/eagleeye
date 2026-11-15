"""scripts/cloud_env.py: parses .env.cloud and refuses anything it shouldn't push."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("cloud_env", ROOT / "scripts" / "cloud_env.py")
cloud_env = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(cloud_env)  # type: ignore[union-attr]

REQUIRED = {n: "x" for n, req in cloud_env.ALLOWED.items() if req}


def test_parse_handles_comments_quotes_and_equals_in_values() -> None:
    text = '# comment\n\nDATABASE_URL="postgresql://u:p@h:5432/db?sslmode=require"\nA=b=c\n'
    assert cloud_env.parse(text) == {
        "DATABASE_URL": "postgresql://u:p@h:5432/db?sslmode=require",
        "A": "b=c",
    }


def test_complete_file_has_no_problems() -> None:
    assert cloud_env.problems(REQUIRED) == []


def test_terraform_managed_names_are_refused() -> None:
    found = cloud_env.problems({**REQUIRED, "ORIGIN_VERIFY_SECRET": "x"})
    assert any("managed by Terraform" in f for f in found)


def test_unknown_empty_and_missing_settings_are_reported() -> None:
    values = {**REQUIRED, "SURPRISE": "x", "SMTP_PASSWORD": ""}
    del values["OPENAI_API_KEY"]
    found = " ".join(cloud_env.problems(values))
    assert "SURPRISE" in found and "SMTP_PASSWORD: empty" in found
    assert "OPENAI_API_KEY: required but missing" in found


def test_bad_lines_are_rejected() -> None:
    try:
        cloud_env.parse("JUST_A_NAME\n")
    except ValueError as exc:
        assert "line 1" in str(exc)
    else:
        raise AssertionError("expected a ValueError")


def test_a_comment_after_a_value_is_dropped_but_hashes_inside_stay() -> None:
    lines = [
        "DATABASE_URL=postgresql://u:p@h:5432/postgres      # eagleeye-demo pooler",
        "OPENAI_API_KEY=sk-abc#def",
        'QDRANT_URL="https://x:6333 # quoted stays"',
    ]
    text = "\n".join(lines)
    assert cloud_env.parse(text) == {
        "DATABASE_URL": "postgresql://u:p@h:5432/postgres",
        "OPENAI_API_KEY": "sk-abc#def",
        "QDRANT_URL": "https://x:6333 # quoted stays",
    }
