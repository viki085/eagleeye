"""Shape-based personal-data detection shared by result previews and dataset profiles.

A value that looks like an email address or a phone number is masked before it is sent to
an LLM provider. Column-level PII flags (catalog, profile) are applied by the callers.
"""

import re
from typing import Any

MASK = "***"
MIN_PHONE_DIGITS = 9
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", re.IGNORECASE)
_PHONE_CHARS = re.compile(r"^\+?[\d\s().-]+$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_PII_NAME = re.compile(
    r"(^|_)(e?mail|phone|mobile|tel|ssn|passport|iban|address|dob|birth(day|date)?"
    r"|first_?name|last_?name|full_?name|surname)(_|$)",
    re.IGNORECASE,
)


def looks_like_email(text: str) -> bool:
    return bool(_EMAIL.search(text))


def looks_like_phone(text: str) -> bool:
    """Phone-shaped: only phone characters and ≥ 9 digits — but never an ISO date/time."""
    s = text.strip()
    if _ISO_DATE.match(s) or not _PHONE_CHARS.match(s):
        return False
    return sum(ch.isdigit() for ch in s) >= MIN_PHONE_DIGITS


def looks_personal(value: Any) -> bool:
    return isinstance(value, str) and (looks_like_email(value) or looks_like_phone(value))


def pii_column_name(name: str) -> bool:
    """Header suggests personal data (email, phone, name, address, date of birth...)."""
    return bool(_PII_NAME.search(name))
