class RunCancelledError(Exception):
    """Raised at a safe point when the user pressed Stop."""


class GuardUnavailableError(Exception):
    """The guard could not classify the message; the run must fail closed."""
