class SqlRejected(Exception):  # noqa: N818 - reads naturally at call sites: `except SqlRejected`
    """A statement failed validation. `user_message` is safe to show and to feed back to the
    SQL agent; it never reveals whether an ungranted table exists."""

    def __init__(self, code: str, user_message: str) -> None:
        super().__init__(f"{code}: {user_message}")
        self.code = code
        self.user_message = user_message


PARSE_ERROR = "PARSE_ERROR"
NOT_SINGLE_SELECT = "NOT_SINGLE_SELECT"
FORBIDDEN_STATEMENT = "FORBIDDEN_STATEMENT"
TABLE_NOT_ALLOWED = "TABLE_NOT_ALLOWED"
UNKNOWN_COLUMN = "UNKNOWN_COLUMN"
COLUMN_RESTRICTED = "COLUMN_RESTRICTED"
FUNCTION_NOT_ALLOWED = "FUNCTION_NOT_ALLOWED"
CARTESIAN_JOIN = "CARTESIAN_JOIN"
TOO_COMPLEX = "TOO_COMPLEX"
