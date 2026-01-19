from __future__ import annotations

import threading
import time
import unittest

from django.test import override_settings

from django_hookflow.circuit_breaker import CircuitBreaker
from django_hookflow.circuit_breaker import CircuitBreakerError
from django_hookflow.circuit_breaker import CircuitState
from django_hookflow.circuit_breaker import get_qstash_circuit_breaker


class TestCircuitBreakerStates(unittest.TestCase):
    """Tests for circuit breaker state transitions."""

    @override_settings(DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True)
    def setUp(self):
        self.cb = CircuitBreaker(name="test")

    @override_settings(DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True)
    def test_initial_state_is_closed(self):
        """Test that circuit breaker starts in CLOSED state."""
        cb = CircuitBreaker(name="test-initial")
        self.assertEqual(cb.state, CircuitState.CLOSED)

    @override_settings(
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD=3,
    )
    def test_transitions_to_open_after_threshold_failures(self):
        """Test transition from CLOSED to OPEN after failure threshold."""
        cb = CircuitBreaker(name="test-threshold")

        # Record failures up to threshold
        for _ in range(3):
            cb.record_failure()

        self.assertEqual(cb.state, CircuitState.OPEN)

    @override_settings(
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5,
    )
    def test_stays_closed_below_threshold(self):
        """Test that circuit stays CLOSED below failure threshold."""
        cb = CircuitBreaker(name="test-below")

        # Record failures below threshold
        for _ in range(4):
            cb.record_failure()

        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertEqual(cb.failure_count, 4)

    @override_settings(
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD=3,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_RECOVERY_TIMEOUT=1,
    )
    def test_transitions_to_half_open_after_timeout(self):
        """Test transition from OPEN to HALF_OPEN after recovery timeout."""
        cb = CircuitBreaker(name="test-recovery")

        # Trip the circuit
        for _ in range(3):
            cb.record_failure()

        self.assertEqual(cb.state, CircuitState.OPEN)

        # Wait for recovery timeout
        time.sleep(1.1)

        # Access state to trigger transition check
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

    @override_settings(
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD=3,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_RECOVERY_TIMEOUT=1,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_HALF_OPEN_REQUESTS=2,
    )
    def test_transitions_to_closed_after_half_open_successes(self):
        """Test transition from HALF_OPEN to CLOSED after successes."""
        cb = CircuitBreaker(name="test-half-open-success")

        # Trip the circuit
        for _ in range(3):
            cb.record_failure()

        # Wait for recovery timeout
        time.sleep(1.1)
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

        # Record successful requests
        cb.record_success()
        cb.record_success()

        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertEqual(cb.failure_count, 0)

    @override_settings(
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD=3,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_RECOVERY_TIMEOUT=1,
    )
    def test_transitions_back_to_open_on_half_open_failure(self):
        """Test transition from HALF_OPEN back to OPEN on failure."""
        cb = CircuitBreaker(name="test-half-open-fail")

        # Trip the circuit
        for _ in range(3):
            cb.record_failure()

        # Wait for recovery timeout
        time.sleep(1.1)
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

        # Record a failure
        cb.record_failure()

        self.assertEqual(cb.state, CircuitState.OPEN)


class TestCircuitBreakerAllowRequest(unittest.TestCase):
    """Tests for allow_request method."""

    @override_settings(
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD=3,
    )
    def test_allow_request_when_closed(self):
        """Test that requests are allowed when circuit is CLOSED."""
        cb = CircuitBreaker(name="test-allow-closed")
        self.assertTrue(cb.allow_request())

    @override_settings(
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD=3,
    )
    def test_deny_request_when_open(self):
        """Test that requests are denied when circuit is OPEN."""
        cb = CircuitBreaker(name="test-deny-open")

        # Trip the circuit
        for _ in range(3):
            cb.record_failure()

        self.assertFalse(cb.allow_request())

    @override_settings(DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=False)
    def test_allow_request_when_disabled(self):
        """Test that requests are always allowed when disabled."""
        cb = CircuitBreaker(name="test-disabled")

        # Even with "failures", should allow
        for _ in range(10):
            cb.record_failure()

        self.assertTrue(cb.allow_request())


class TestCircuitBreakerCall(unittest.TestCase):
    """Tests for the call() method."""

    @override_settings(
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD=3,
    )
    def test_call_executes_function_when_closed(self):
        """Test that call() executes function when circuit is CLOSED."""
        cb = CircuitBreaker(name="test-call-closed")

        result = cb.call(lambda x: x * 2, 5)
        self.assertEqual(result, 10)

    @override_settings(
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD=3,
    )
    def test_call_raises_error_when_open(self):
        """Test that call() raises CircuitBreakerError when OPEN."""
        cb = CircuitBreaker(name="test-call-open")

        # Trip the circuit
        for _ in range(3):
            cb.record_failure()

        with self.assertRaises(CircuitBreakerError) as ctx:
            cb.call(lambda: "test")

        self.assertEqual(ctx.exception.state, CircuitState.OPEN)

    @override_settings(
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD=3,
    )
    def test_call_records_success_on_success(self):
        """Test that call() records success when function succeeds."""
        cb = CircuitBreaker(name="test-call-success")

        # Add some failures first
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.failure_count, 2)

        # Successful call should reset failures
        cb.call(lambda: "success")
        self.assertEqual(cb.failure_count, 0)

    @override_settings(
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD=3,
    )
    def test_call_records_failure_on_exception(self):
        """Test that call() records failure when function raises."""
        cb = CircuitBreaker(name="test-call-failure")

        def failing_func():
            raise ValueError("test error")

        with self.assertRaises(ValueError):
            cb.call(failing_func)

        self.assertEqual(cb.failure_count, 1)


class TestCircuitBreakerReset(unittest.TestCase):
    """Tests for manual reset."""

    @override_settings(
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD=3,
    )
    def test_reset_returns_to_closed_state(self):
        """Test that reset() returns circuit to CLOSED state."""
        cb = CircuitBreaker(name="test-reset")

        # Trip the circuit
        for _ in range(3):
            cb.record_failure()

        self.assertEqual(cb.state, CircuitState.OPEN)

        # Reset
        cb.reset()

        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertEqual(cb.failure_count, 0)


class TestCircuitBreakerStatus(unittest.TestCase):
    """Tests for status reporting."""

    @override_settings(
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_RECOVERY_TIMEOUT=30,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_HALF_OPEN_REQUESTS=3,
    )
    def test_get_status_returns_all_info(self):
        """Test that get_status() returns all relevant information."""
        cb = CircuitBreaker(name="test-status")
        cb.record_failure()
        cb.record_failure()

        status = cb.get_status()

        self.assertEqual(status["name"], "test-status")
        self.assertTrue(status["enabled"])
        self.assertEqual(status["state"], "closed")
        self.assertEqual(status["failure_count"], 2)
        self.assertEqual(status["failure_threshold"], 5)
        self.assertEqual(status["recovery_timeout"], 30)
        self.assertEqual(status["half_open_requests"], 3)


class TestCircuitBreakerThreadSafety(unittest.TestCase):
    """Tests for thread safety."""

    @override_settings(
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_ENABLED=True,
        DJANGO_HOOKFLOW_CIRCUIT_BREAKER_FAILURE_THRESHOLD=100,
    )
    def test_concurrent_failure_recording(self):
        """Test that concurrent failure recording is thread-safe."""
        cb = CircuitBreaker(name="test-thread-safe")

        def record_failures():
            for _ in range(50):
                cb.record_failure()

        threads = [threading.Thread(target=record_failures) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have exactly 200 failures
        self.assertEqual(cb.failure_count, 100)  # Threshold reached


class TestGetQStashCircuitBreaker(unittest.TestCase):
    """Tests for the singleton getter."""

    def test_returns_same_instance(self):
        """Test that get_qstash_circuit_breaker returns the same instance."""
        cb1 = get_qstash_circuit_breaker()
        cb2 = get_qstash_circuit_breaker()
        self.assertIs(cb1, cb2)

    def test_has_correct_name(self):
        """Test that the QStash circuit breaker has the correct name."""
        cb = get_qstash_circuit_breaker()
        status = cb.get_status()
        self.assertEqual(status["name"], "qstash")


if __name__ == "__main__":
    unittest.main()
