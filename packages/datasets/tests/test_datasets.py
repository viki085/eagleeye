import io
import zipfile

import pandas as pd
import pytest
from eagleeye_datasets.convert import convert_csv, convert_xlsx
from eagleeye_datasets.models import DatasetError, Limits
from eagleeye_datasets.names import safe_names
from eagleeye_datasets.profile import kind_of, profile_parquet
from eagleeye_datasets.render import profile_digest
from openpyxl import Workbook

CSV = (
    "Region,Month,Target (EUR),Owner Email,Notes\n"
    "EMEA,2026-01-01,1000.5,a@example.com,ok\n"
    "EMEA,2026-02-01,1200,b@example.com,\n"
    "APAC,2026-01-01,800,c@example.com,ok\n"
    "APAC,2026-02-01,,d@example.com,ok\n"
    "APAC,2026-02-01,,d@example.com,ok\n"
)


def frame(parquet: bytes) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(parquet))


def test_safe_names_normalise_dedupe_and_keep_originals() -> None:
    names, mapping = safe_names(["Order ID", "Order ID", "2024 Sales", None, "select", "  "])
    assert names == ["order_id", "order_id_2", "c_2024_sales", "column_4", "select_col", "column_6"]
    assert mapping["c_2024_sales"] == "2024 Sales" and mapping["column_4"] == "column_4"


def test_csv_types_names_and_values_match_pandas() -> None:
    out = convert_csv(CSV.encode())
    assert out.row_count == 5 and out.sheet == ""
    assert [c["name"] for c in out.columns] == [
        "region",
        "month",
        "target_eur",
        "owner_email",
        "notes",
    ]
    types = {c["name"]: kind_of(c["type"]) for c in out.columns}
    assert types["target_eur"] == "numeric" and types["month"] == "temporal"
    assert out.column_map["target_eur"] == "Target (EUR)"
    reference = pd.read_csv(io.StringIO(CSV))
    assert frame(out.parquet)["target_eur"].sum() == pytest.approx(reference["Target (EUR)"].sum())


@pytest.mark.parametrize(
    "raw",
    [
        "﻿a;b\n1;x\n2;y\n".encode(),  # BOM + semicolon
        b"a\tb\n1\tx\n2\ty\n",  # TSV
        "a,b\n1,caf\xe9\n2,y\n".encode("cp1252"),  # not UTF-8
    ],
)
def test_csv_dialects_and_encodings(raw: bytes) -> None:
    out = convert_csv(raw)
    assert [c["name"] for c in out.columns] == ["a", "b"] and out.row_count == 2


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        (b"PK\x03\x04\x00\x00binary", "text file"),
        (b"a,b\n", "no data rows"),
        (b"a,b\n1,2\n3,4\n5,6\n", "Too many rows"),
    ],
)
def test_csv_rejections(raw: bytes, fragment: str) -> None:
    with pytest.raises(DatasetError) as exc:
        convert_csv(raw, Limits(max_rows=2))
    assert fragment in exc.value.user_message


def _workbook() -> bytes:
    wb = Workbook()
    first = wb.active
    first.title = "Targets"
    first.append(["Region", "Target", "Double"])
    first.append(["EMEA", 100, "=B2*2"])  # formula: never evaluated, no cached value
    first.append(["APAC", 250.5, "=B3*2"])
    second = wb.create_sheet("Mixed")
    second.append(["id", "value"])
    second.append([1, "x"])
    second.append([2, 3])
    wb.create_sheet("Empty")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_values_only_one_dataset_per_sheet() -> None:
    sheets = convert_xlsx(_workbook())
    assert [s.sheet for s in sheets] == ["Targets", "Mixed"]  # empty sheet skipped
    targets = frame(sheets[0].parquet)
    assert targets["target"].tolist() == [100, 250.5]
    assert targets["double"].isna().all()  # formulas are not computed
    assert frame(sheets[1].parquet)["value"].tolist() == ["x", "3"]  # mixed → text


def test_xlsx_rejects_non_workbooks_and_zip_bombs(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(DatasetError):
        convert_xlsx(b"not a zip")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/big.xml", b"0" * 2_000_000)
    monkeypatch.setattr("eagleeye_datasets.convert.MAX_UNZIPPED_BYTES", 1_000_000)
    with pytest.raises(DatasetError) as exc:
        convert_xlsx(buf.getvalue())
    assert "too large" in exc.value.user_message


def test_profile_matches_pandas_reference() -> None:
    out = convert_csv(CSV.encode())
    profile = profile_parquet(out.parquet, out.column_map)
    reference = pd.read_csv(io.StringIO(CSV))
    assert profile["row_count"] == 5 and profile["column_count"] == 5
    assert profile["duplicate_rows"] == 1
    cols = {c["name"]: c for c in profile["columns"]}
    target = cols["target_eur"]
    assert target["null_pct"] == 40.0 and target["distinct"] == 3
    # profiles round floats to 6 significant figures
    assert target["mean"] == pytest.approx(reference["Target (EUR)"].mean(), rel=1e-5)
    assert target["median"] == pytest.approx(reference["Target (EUR)"].median(), rel=1e-5)
    assert target["min"] == 800 and target["max"] == 1200
    assert cols["region"]["top"][0] == {"value": "APAC", "count": 3}
    assert cols["month"]["min"].startswith("2026-01-01")
    assert cols["target_eur"]["original"] == "Target (EUR)"


def test_profile_flags_pii_and_masks_the_sample() -> None:
    out = convert_csv(CSV.encode())
    profile = profile_parquet(out.parquet, out.column_map)
    email = next(c for c in profile["columns"] if c["name"] == "owner_email")
    assert "pii" in email["flags"] and "top" not in email
    idx = profile["sample"]["columns"].index("owner_email")
    assert {row[idx] for row in profile["sample"]["rows"]} == {"***"}
    assert any("personal data" in w for w in profile["warnings"])
    assert "a@example.com" not in profile_digest("targets", profile, with_sample=True)


def test_profile_flags_and_correlations() -> None:
    rows = "\n".join(f"{i},{i * 2},{7},{'x' if i % 2 else ''}" for i in range(1, 41))
    out = convert_csv(f"id,double,constant,sparse\n{rows}\n".encode())
    profile = profile_parquet(out.parquet)
    cols = {c["name"]: c for c in profile["columns"]}
    assert "id_like" in cols["id"]["flags"] and "constant" in cols["constant"]["flags"]
    assert cols["sparse"]["null_pct"] == 50.0
    digest = profile_digest("t", profile)
    assert "40 rows × 4 columns" in digest and "constant" in digest


def test_correlation_reported_for_related_numeric_columns() -> None:
    rows = "\n".join(f"{i % 7},{(i % 7) * 3 + 1},{i}" for i in range(60))
    profile = profile_parquet(convert_csv(f"a,b,n\n{rows}\n".encode()).parquet)
    assert {"a": "a", "b": "b", "r": 1.0} in profile["correlations"]
