class IngestError(Exception):
    """Base. `user_message` is safe to show in the UI; details go to logs only."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class PermanentIngestError(IngestError):
    """Retrying will not help (bad file type, no text, ...)."""


class TransientIngestError(IngestError):
    """Network / provider hiccup; the task is retried with backoff."""
