from __future__ import annotations

from dataclasses import dataclass

# Exceptions that should NOT be retried (deterministic failures)
NON_RETRYABLE_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    NotImplementedError,
    AssertionError,
)


def is_retryable_error(exception: Exception) -> bool:
    """
    Determine if an error should be retried.

    Non-retryable errors include:
    - ValueError, TypeError, KeyError, AttributeError (programming errors)
    - NotImplementedError, AssertionError (logic errors)
    - Errors with "not found" in the message (missing resources)
    - Errors with "invalid" in the message (validation failures)

    All other errors are considered potentially transient and retryable.

    Args:
        exception: The exception to check

    Returns:
        True if the error should be retried, False otherwise
    """
    # Check exception type
    if isinstance(exception, NON_RETRYABLE_ERRORS):
        return False

    # Check for common non-retryable error messages
    error_msg = str(exception).lower()
    non_retryable_patterns = [
        "not found",
        "does not exist",
        "invalid",
        "missing required",
        "permission denied",
        "unauthorized",
        "forbidden",
    ]

    for pattern in non_retryable_patterns:
        if pattern in error_msg:
            return False

    return True


@dataclass
class RetryConfig:
    """Configuration for retry behavior with exponential backoff."""

    max_retries: int = 3
    initial_delay_seconds: int = 1
    max_delay_seconds: int = 300
    exponential_base: float = 2.0

    def get_delay_for_attempt(self, attempt: int) -> int:
        """
        Calculate delay for an attempt using exponential backoff.

        Args:
            attempt: The current attempt number (0-indexed)

        Returns:
            The delay in seconds, capped at max_delay_seconds
        """
        delay = self.initial_delay_seconds * (self.exponential_base**attempt)
        return min(int(delay), self.max_delay_seconds)


DEFAULT_RETRY_CONFIG = RetryConfig()


def should_retry(attempt: int, config: RetryConfig | None = None) -> bool:
    """
    Determine if a retry should be attempted.

    Args:
        attempt: The current attempt number (0-indexed)
        config: Optional retry config. Uses DEFAULT_RETRY_CONFIG if None.

    Returns:
        True if another retry should be attempted, False otherwise
    """
    if config is None:
        config = DEFAULT_RETRY_CONFIG
    return attempt < config.max_retries


def get_retry_delay(attempt: int, config: RetryConfig | None = None) -> int:
    """
    Get the delay in seconds before the next retry attempt.

    Args:
        attempt: The current attempt number (0-indexed)
        config: Optional retry config. Uses DEFAULT_RETRY_CONFIG if None.

    Returns:
        The delay in seconds for the next retry
    """
    if config is None:
        config = DEFAULT_RETRY_CONFIG
    return config.get_delay_for_attempt(attempt)
