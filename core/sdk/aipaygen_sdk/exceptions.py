"""Exception hierarchy for AiPayGen SDK."""


class AiPayGenError(Exception):
    """Base exception for all AiPayGen SDK errors."""

    def __init__(self, message: str, status_code: int = 0, response: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response or {}


class AuthError(AiPayGenError):
    """Raised on 401/403 — invalid or missing API key."""

    def __init__(self, message: str = "Invalid or missing API key", response: dict = None):
        super().__init__(message, status_code=401, response=response)


class PaymentRequired(AiPayGenError):
    """Raised on 402 when auto_pay is disabled or payment fails."""

    def __init__(self, message: str = "Payment required", payment_info: dict = None, response: dict = None):
        super().__init__(message, status_code=402, response=response)
        self.payment_info = payment_info or {}


class RateLimitError(AiPayGenError):
    """Raised on 429 after exhausting retries."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: float = 0, response: dict = None):
        super().__init__(message, status_code=429, response=response)
        self.retry_after = retry_after


class ServerError(AiPayGenError):
    """Raised on 5xx server errors."""

    def __init__(self, message: str = "Server error", status_code: int = 500, response: dict = None):
        super().__init__(message, status_code=status_code, response=response)
