import pytest
from app.errors import ApiException
from app.services import uploads


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd.txt", "passwd.txt"),
        ("C:\\Users\\x\\notes.md", "notes.md"),
        ("bad<>:name?.txt", "badname.txt"),
        (None, "upload"),
        ("...", "upload"),
    ],
)
def test_safe_filename(raw: str | None, expected: str) -> None:
    assert uploads.safe_filename(raw) == expected


def test_title_and_key() -> None:
    assert uploads.title_from("Q3_sales  report.pdf") == "Q3 sales report"
    assert uploads.object_key("personal", "abc", ".pdf") == "personal/abc/original.pdf"


def test_require_supported_rejects_unknown() -> None:
    assert uploads.require_supported("a.PDF") == (".pdf", "application/pdf")
    with pytest.raises(ApiException) as exc:
        uploads.require_supported("a.exe")
    assert exc.value.status_code == 415
