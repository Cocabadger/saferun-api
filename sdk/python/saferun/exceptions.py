"""Custom exceptions for SafeRun SDK."""

class SafeRunError(Exception):
    """Base exception for SafeRun SDK."""


class SafeRunAPIError(SafeRunError):
    """Raised when API returns an error response."""

    def __init__(self, status_code: int, message: str):
        super().__init__(f"SafeRun API error ({status_code}): {message}")
        self.status_code = status_code
        self.message = message


class SafeRunApprovalTimeout(SafeRunError):
    """Raised when waiting for approval times out."""

    def __init__(self, change_id: str, timeout: int):
        super().__init__(f"Timed out waiting for approval of change {change_id} after {timeout}s")
        self.change_id = change_id
        self.timeout = timeout
