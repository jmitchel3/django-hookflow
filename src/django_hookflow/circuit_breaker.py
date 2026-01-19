from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Any
from typing import Callable
from typing import TypeVar

from django.conf import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Possible states of the circuit breaker."""

    CLOSED = "closed"  # Normal operation, requests flow through
    OPEN = "open"  # Circuit tripped, requests are rejected
    HALF_OPEN = "half_open"  # Testing if service has recovered


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open and request is rejected."""

    def __init__(self, message: str, state: CircuitState) -> None:
        super().__init__(message)
        self.state = state


class CircuitBreaker:
    """
    Thread-safe circuit breaker implementation.

    The circuit breaker prevents cascading failures by failing fast when
    a service is experiencing problems. It has three states:

    - CLOSED: Normal operation. Requests flow through and failures are
      tracked. If failures exceed the threshold, transitions to OPEN.

    - OPEN: Circuit is tripped. All requests are immediately rejected
      without attempting the operation. After recovery_timeout, transitions
      to HALF_OPEN.

    - HALF_OPEN: Testing recovery. A limited number of requests are allowed
      through. If they succeed, transitions back to CLOSED. If any fail,
      transitions back to OPEN.

    Settings:
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED: Enable circuit breaker
            (default: False)
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD: Number of
            failures before opening circuit (default: 5)
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_RECOVERY_TIMEOUT: Seconds to wait
            before trying half-open (default: 30)
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_HALF_OPEN_REQUESTS: Number of
            successful requests needed to close circuit (default: 3)

    Note:
        This implementation uses in-process state, which means each process
        in a multi-process deployment has its own circuit breaker state.
        For shared state across processes, consider using Redis or another
        distributed store (not implemented here).
    """

    def __init__(self, name: str = "default") -> None:
        """
        Initialize the circuit breaker.

        Args:
            name: Identifier for this circuit breaker (for logging)
        """
        self._name = name
        self._lock = threading.RLock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        """Current state of the circuit breaker."""
        with self._lock:
            self._check_state_transition()
            return self._state

    @property
    def failure_count(self) -> int:
        """Current failure count."""
        with self._lock:
            return self._failure_count

    def _is_enabled(self) -> bool:
        """Check if circuit breaker is enabled in settings."""
        return getattr(
            settings,
            "DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED",
            False,
        )

    def _get_failure_threshold(self) -> int:
        """Get the failure threshold from settings."""
        return getattr(
            settings,
            "DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD",
            5,
        )

    def _get_recovery_timeout(self) -> int:
        """Get the recovery timeout from settings."""
        return getattr(
            settings,
            "DJANGO_HOOKFLOW_CIRCUIT_BREAKER_RECOVERY_TIMEOUT",
            30,
        )

    def _get_half_open_requests(self) -> int:
        """Get the number of successful half-open requests needed."""
        return getattr(
            settings,
            "DJANGO_HOOKFLOW_CIRCUIT_BREAKER_HALF_OPEN_REQUESTS",
            3,
        )

    def _check_state_transition(self) -> None:
        """
        Check if state should transition based on timeouts.

        Must be called with lock held.
        """
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            recovery_timeout = self._get_recovery_timeout()
            if time.time() - self._opened_at >= recovery_timeout:
                logger.info(
                    "Circuit breaker '%s' transitioning from OPEN to "
                    "HALF_OPEN after %ds",
                    self._name,
                    recovery_timeout,
                )
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0

    def _transition_to_open(self) -> None:
        """
        Transition to OPEN state.

        Must be called with lock held.
        """
        self._state = CircuitState.OPEN
        self._opened_at = time.time()
        logger.warning(
            "Circuit breaker '%s' OPENED after %d failures",
            self._name,
            self._failure_count,
        )

    def _transition_to_closed(self) -> None:
        """
        Transition to CLOSED state.

        Must be called with lock held.
        """
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at = None
        logger.info(
            "Circuit breaker '%s' CLOSED - service recovered",
            self._name,
        )

    def record_success(self) -> None:
        """Record a successful call."""
        if not self._is_enabled():
            return

        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                half_open_requests = self._get_half_open_requests()
                if self._success_count >= half_open_requests:
                    self._transition_to_closed()
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success in closed state
                if self._failure_count > 0:
                    self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        if not self._is_enabled():
            return

        with self._lock:
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open immediately reopens
                logger.warning(
                    "Circuit breaker '%s' failure in HALF_OPEN state, "
                    "reopening",
                    self._name,
                )
                self._transition_to_open()

            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                failure_threshold = self._get_failure_threshold()
                if self._failure_count >= failure_threshold:
                    self._transition_to_open()
                else:
                    logger.debug(
                        "Circuit breaker '%s' failure %d/%d",
                        self._name,
                        self._failure_count,
                        failure_threshold,
                    )

    def allow_request(self) -> bool:
        """
        Check if a request should be allowed through.

        Returns:
            True if request should proceed, False if circuit is open
        """
        if not self._is_enabled():
            return True

        with self._lock:
            self._check_state_transition()
            return self._state != CircuitState.OPEN

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Execute a function with circuit breaker protection.

        Args:
            func: The function to call
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            The result of the function call

        Raises:
            CircuitBreakerError: If the circuit is open
            Exception: Any exception raised by the function
        """
        if not self._is_enabled():
            return func(*args, **kwargs)

        if not self.allow_request():
            raise CircuitBreakerError(
                f"Circuit breaker '{self._name}' is OPEN - request rejected",
                state=self._state,
            )

        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    def reset(self) -> None:
        """
        Manually reset the circuit breaker to CLOSED state.

        Useful for testing or manual intervention.
        """
        with self._lock:
            self._transition_to_closed()
            logger.info(
                "Circuit breaker '%s' manually reset to CLOSED",
                self._name,
            )

    def get_status(self) -> dict[str, Any]:
        """
        Get the current status of the circuit breaker.

        Returns:
            Dictionary with state, failure_count, and other metrics
        """
        with self._lock:
            self._check_state_transition()
            return {
                "name": self._name,
                "enabled": self._is_enabled(),
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "failure_threshold": self._get_failure_threshold(),
                "recovery_timeout": self._get_recovery_timeout(),
                "half_open_requests": self._get_half_open_requests(),
                "last_failure_time": self._last_failure_time,
                "opened_at": self._opened_at,
            }


# Singleton instance for QStash client
_qstash_circuit_breaker: CircuitBreaker | None = None
_circuit_breaker_lock = threading.Lock()


def get_qstash_circuit_breaker() -> CircuitBreaker:
    """
    Get the singleton circuit breaker instance for QStash.

    Returns:
        The CircuitBreaker instance for QStash operations
    """
    global _qstash_circuit_breaker

    if _qstash_circuit_breaker is None:
        with _circuit_breaker_lock:
            if _qstash_circuit_breaker is None:
                _qstash_circuit_breaker = CircuitBreaker(name="qstash")

    return _qstash_circuit_breaker
