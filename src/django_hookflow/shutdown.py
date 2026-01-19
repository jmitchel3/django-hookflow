from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager

from django.conf import settings

logger = logging.getLogger(__name__)


class ShutdownManager:
    """
    Manages graceful shutdown of workflow processing.

    This class tracks in-flight workflow requests and provides a mechanism
    to stop accepting new requests while waiting for in-flight requests
    to complete before shutdown.

    Features:
        - Tracks in-flight requests by run_id
        - SIGTERM handler to initiate graceful shutdown
        - Configurable shutdown timeout
        - Thread-safe request tracking

    Settings:
        DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED: Enable graceful shutdown
            (default: True)
        DJANGO_HOOKFLOW_SHUTDOWN_TIMEOUT: Seconds to wait for in-flight
            requests to complete (default: 30)

    Note:
        This works best in single-process deployments. In multi-process
        deployments (e.g., gunicorn with multiple workers), each worker
        has its own ShutdownManager instance. The orchestration layer
        (e.g., Kubernetes, systemd) should send SIGTERM to initiate
        graceful shutdown.
    """

    def __init__(self) -> None:
        """Initialize the shutdown manager."""
        self._lock = threading.RLock()
        self._shutting_down = False
        self._shutdown_complete = threading.Event()
        self._in_flight: dict[str, float] = {}  # run_id -> start_time
        self._signal_handlers_installed = False

    def _is_enabled(self) -> bool:
        """Check if graceful shutdown is enabled."""
        return getattr(
            settings,
            "DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED",
            True,
        )

    def _get_shutdown_timeout(self) -> int:
        """Get the shutdown timeout in seconds."""
        return getattr(
            settings,
            "DJANGO_HOOKFLOW_SHUTDOWN_TIMEOUT",
            30,
        )

    @property
    def is_shutting_down(self) -> bool:
        """Check if shutdown has been initiated."""
        with self._lock:
            return self._shutting_down

    @property
    def in_flight_count(self) -> int:
        """Get the number of in-flight requests."""
        with self._lock:
            return len(self._in_flight)

    def get_in_flight_requests(self) -> dict[str, float]:
        """
        Get a copy of in-flight request tracking data.

        Returns:
            Dictionary mapping run_id to request start time
        """
        with self._lock:
            return dict(self._in_flight)

    def track_request_start(self, run_id: str) -> bool:
        """
        Track the start of a workflow request.

        Args:
            run_id: The workflow run identifier

        Returns:
            True if request should proceed, False if shutdown is in progress
        """
        if not self._is_enabled():
            return True

        with self._lock:
            if self._shutting_down:
                logger.info(
                    "Rejecting request during shutdown: run_id=%s",
                    run_id,
                )
                return False

            self._in_flight[run_id] = time.time()
            logger.debug(
                "Tracking request start: run_id=%s, in_flight=%d",
                run_id,
                len(self._in_flight),
            )
            return True

    def track_request_end(self, run_id: str) -> None:
        """
        Track the end of a workflow request.

        Args:
            run_id: The workflow run identifier
        """
        if not self._is_enabled():
            return

        with self._lock:
            if run_id in self._in_flight:
                elapsed = time.time() - self._in_flight[run_id]
                del self._in_flight[run_id]
                logger.debug(
                    "Tracking request end: run_id=%s, elapsed=%.2fs, "
                    "in_flight=%d",
                    run_id,
                    elapsed,
                    len(self._in_flight),
                )

                # Signal completion if shutting down and no more in-flight
                if self._shutting_down and len(self._in_flight) == 0:
                    self._shutdown_complete.set()

    @contextmanager
    def track_request(self, run_id: str) -> Generator[bool]:
        """
        Context manager to track a request's lifecycle.

        Args:
            run_id: The workflow run identifier

        Yields:
            True if request should proceed, False if shutdown in progress
        """
        allowed = self.track_request_start(run_id)
        try:
            yield allowed
        finally:
            if allowed:
                self.track_request_end(run_id)

    def initiate_shutdown(self) -> None:
        """
        Initiate graceful shutdown.

        Marks the manager as shutting down and waits for in-flight
        requests to complete (up to the configured timeout).
        """
        if not self._is_enabled():
            logger.info("Graceful shutdown is disabled")
            return

        with self._lock:
            if self._shutting_down:
                logger.debug("Shutdown already in progress")
                return

            self._shutting_down = True
            in_flight = len(self._in_flight)

            if in_flight == 0:
                logger.info("No in-flight requests, shutdown complete")
                self._shutdown_complete.set()
                return

            logger.info(
                "Graceful shutdown initiated, waiting for %d in-flight "
                "request(s)",
                in_flight,
            )

        # Wait for completion outside the lock
        timeout = self._get_shutdown_timeout()
        completed = self._shutdown_complete.wait(timeout=timeout)

        if completed:
            logger.info("Graceful shutdown complete, all requests finished")
        else:
            with self._lock:
                remaining = len(self._in_flight)
            logger.warning(
                "Graceful shutdown timeout (%ds) exceeded, %d request(s) "
                "still in-flight",
                timeout,
                remaining,
            )

    def _handle_sigterm(
        self,
        signum: int,
        frame: object,
    ) -> None:
        """
        Signal handler for SIGTERM.

        Initiates graceful shutdown when SIGTERM is received.
        """
        logger.info("Received SIGTERM, initiating graceful shutdown")
        self.initiate_shutdown()

    def install_signal_handlers(self) -> None:
        """
        Install signal handlers for graceful shutdown.

        Installs handlers for SIGTERM. Safe to call multiple times.
        """
        if not self._is_enabled():
            logger.debug("Graceful shutdown disabled, skipping signal setup")
            return

        with self._lock:
            if self._signal_handlers_installed:
                return

            try:
                signal.signal(signal.SIGTERM, self._handle_sigterm)
                self._signal_handlers_installed = True
                logger.debug("SIGTERM handler installed for graceful shutdown")
            except (ValueError, OSError) as e:
                # Signal handlers can only be set in main thread
                logger.debug(
                    "Could not install signal handler (may not be main "
                    "thread): %s",
                    e,
                )

    def reset(self) -> None:
        """
        Reset the shutdown manager state.

        Useful for testing. Clears shutdown flag and in-flight tracking.
        """
        with self._lock:
            self._shutting_down = False
            self._shutdown_complete.clear()
            self._in_flight.clear()
            logger.debug("Shutdown manager reset")

    def get_status(self) -> dict[str, object]:
        """
        Get the current status of the shutdown manager.

        Returns:
            Dictionary with shutdown state and metrics
        """
        with self._lock:
            return {
                "enabled": self._is_enabled(),
                "shutting_down": self._shutting_down,
                "in_flight_count": len(self._in_flight),
                "in_flight_requests": list(self._in_flight.keys()),
                "shutdown_timeout": self._get_shutdown_timeout(),
                "signal_handlers_installed": self._signal_handlers_installed,
            }


# Singleton instance
_shutdown_manager: ShutdownManager | None = None
_shutdown_manager_lock = threading.Lock()


def get_shutdown_manager() -> ShutdownManager:
    """
    Get the singleton ShutdownManager instance.

    Returns:
        The ShutdownManager instance
    """
    global _shutdown_manager

    if _shutdown_manager is None:
        with _shutdown_manager_lock:
            if _shutdown_manager is None:
                _shutdown_manager = ShutdownManager()

    return _shutdown_manager
