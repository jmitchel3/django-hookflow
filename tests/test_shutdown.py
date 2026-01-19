from __future__ import annotations

import json
import threading
import time
import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from django.test import RequestFactory
from django.test import override_settings

from django_hookflow import workflow
from django_hookflow.shutdown import ShutdownManager
from django_hookflow.shutdown import get_shutdown_manager
from django_hookflow.workflows.registry import _workflow_registry
from django_hookflow.workflows.views import workflow_webhook_raw


class TestShutdownManager(unittest.TestCase):
    """Tests for the ShutdownManager class."""

    def setUp(self):
        self.manager = ShutdownManager()

    @override_settings(DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED=True)
    def test_initial_state(self):
        """Test initial state of shutdown manager."""
        manager = ShutdownManager()
        self.assertFalse(manager.is_shutting_down)
        self.assertEqual(manager.in_flight_count, 0)

    @override_settings(DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED=True)
    def test_track_request_start(self):
        """Test tracking request start."""
        manager = ShutdownManager()

        result = manager.track_request_start("run-1")

        self.assertTrue(result)
        self.assertEqual(manager.in_flight_count, 1)
        self.assertIn("run-1", manager.get_in_flight_requests())

    @override_settings(DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED=True)
    def test_track_request_end(self):
        """Test tracking request end."""
        manager = ShutdownManager()
        manager.track_request_start("run-1")

        manager.track_request_end("run-1")

        self.assertEqual(manager.in_flight_count, 0)
        self.assertNotIn("run-1", manager.get_in_flight_requests())

    @override_settings(DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED=True)
    def test_track_request_context_manager(self):
        """Test the track_request context manager."""
        manager = ShutdownManager()

        with manager.track_request("run-1") as allowed:
            self.assertTrue(allowed)
            self.assertEqual(manager.in_flight_count, 1)

        self.assertEqual(manager.in_flight_count, 0)

    @override_settings(DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED=True)
    def test_reject_new_requests_during_shutdown(self):
        """Test that new requests are rejected during shutdown."""
        manager = ShutdownManager()

        # Simulate an in-flight request
        manager.track_request_start("run-1")

        # Start shutdown in a separate thread (non-blocking)
        def do_shutdown():
            manager.initiate_shutdown()

        shutdown_thread = threading.Thread(target=do_shutdown)
        shutdown_thread.start()

        # Give it a moment to set the shutdown flag
        time.sleep(0.1)

        # New request should be rejected
        result = manager.track_request_start("run-2")
        self.assertFalse(result)

        # Clean up
        manager.track_request_end("run-1")
        shutdown_thread.join(timeout=2)

    @override_settings(
        DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED=True,
        DJANGO_HOOKFLOW_SHUTDOWN_TIMEOUT=1,
    )
    def test_shutdown_waits_for_in_flight(self):
        """Test that shutdown waits for in-flight requests."""
        manager = ShutdownManager()
        manager.track_request_start("run-1")

        # Start shutdown in a separate thread
        completed = []

        def do_shutdown():
            manager.initiate_shutdown()
            completed.append(True)

        shutdown_thread = threading.Thread(target=do_shutdown)
        shutdown_thread.start()

        # Give shutdown a moment to start waiting
        time.sleep(0.2)

        # Complete the in-flight request
        manager.track_request_end("run-1")

        # Shutdown should complete
        shutdown_thread.join(timeout=2)
        self.assertTrue(len(completed) > 0)

    @override_settings(
        DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED=True,
        DJANGO_HOOKFLOW_SHUTDOWN_TIMEOUT=1,
    )
    def test_shutdown_timeout(self):
        """Test that shutdown times out if requests don't complete."""
        manager = ShutdownManager()
        manager.track_request_start("run-1")

        # Start shutdown
        start_time = time.time()
        manager.initiate_shutdown()
        elapsed = time.time() - start_time

        # Should have waited approximately the timeout duration
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertLess(elapsed, 2)

        # Request is still tracked
        self.assertEqual(manager.in_flight_count, 1)

    @override_settings(DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED=True)
    def test_shutdown_completes_immediately_if_no_requests(self):
        """Test that shutdown completes immediately with no in-flight."""
        manager = ShutdownManager()

        start_time = time.time()
        manager.initiate_shutdown()
        elapsed = time.time() - start_time

        # Should complete very quickly
        self.assertLess(elapsed, 0.5)

    @override_settings(DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED=True)
    def test_reset(self):
        """Test the reset method."""
        manager = ShutdownManager()
        manager.track_request_start("run-1")

        manager.reset()

        self.assertFalse(manager.is_shutting_down)
        self.assertEqual(manager.in_flight_count, 0)

    @override_settings(DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED=True)
    def test_get_status(self):
        """Test the get_status method."""
        manager = ShutdownManager()
        manager.track_request_start("run-1")

        status = manager.get_status()

        self.assertTrue(status["enabled"])
        self.assertFalse(status["shutting_down"])
        self.assertEqual(status["in_flight_count"], 1)
        self.assertIn("run-1", status["in_flight_requests"])

    @override_settings(DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED=False)
    def test_disabled_always_allows_requests(self):
        """Test that requests are always allowed when disabled."""
        manager = ShutdownManager()

        # Even during "shutdown", should allow
        manager._shutting_down = True

        result = manager.track_request_start("run-1")
        self.assertTrue(result)


class TestShutdownManagerThreadSafety(unittest.TestCase):
    """Tests for thread safety of ShutdownManager."""

    @override_settings(DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED=True)
    def test_concurrent_request_tracking(self):
        """Test concurrent request tracking is thread-safe."""
        manager = ShutdownManager()

        def track_requests(start_id):
            for i in range(100):
                run_id = f"run-{start_id}-{i}"
                manager.track_request_start(run_id)
                manager.track_request_end(run_id)

        threads = [
            threading.Thread(target=track_requests, args=(i,))
            for i in range(4)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All requests should have been cleaned up
        self.assertEqual(manager.in_flight_count, 0)


class TestGetShutdownManager(unittest.TestCase):
    """Tests for the singleton getter."""

    def test_returns_same_instance(self):
        """Test that get_shutdown_manager returns the same instance."""
        manager1 = get_shutdown_manager()
        manager2 = get_shutdown_manager()
        self.assertIs(manager1, manager2)


class TestWorkflowWebhookShutdown(unittest.TestCase):
    """Tests for shutdown handling in workflow webhook."""

    def setUp(self):
        _workflow_registry.clear()
        self.factory = RequestFactory()

    @override_settings(
        DJANGO_HOOKFLOW_RATE_LIMIT=None,
        DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED=True,
    )
    @patch("django_hookflow.workflows.views.verify_qstash_signature")
    @patch("django_hookflow.workflows.views.get_shutdown_manager")
    def test_rejects_request_during_shutdown(
        self,
        mock_get_manager,
        mock_verify,
    ):
        """Test that webhook rejects requests during shutdown."""
        mock_verify.return_value = True

        # Mock a shutting down manager
        mock_manager = MagicMock()
        mock_manager.is_shutting_down = True
        mock_get_manager.return_value = mock_manager

        @workflow(workflow_id="test-shutdown-wf")
        def test_workflow(ctx):
            return "result"

        payload = {
            "workflow_id": "test-shutdown-wf",
            "run_id": "test-run",
            "data": {},
            "completed_steps": {},
        }

        request = self.factory.post(
            "/hookflow/workflow/test-shutdown-wf/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        response = workflow_webhook_raw(
            request, workflow_id="test-shutdown-wf"
        )

        self.assertEqual(response.status_code, 503)
        response_data = json.loads(response.content)
        self.assertEqual(response_data["error"], "Service is shutting down")

    @override_settings(
        DJANGO_HOOKFLOW_RATE_LIMIT=None,
        DJANGO_HOOKFLOW_GRACEFUL_SHUTDOWN_ENABLED=True,
    )
    @patch("django_hookflow.workflows.views.verify_qstash_signature")
    @patch("django_hookflow.workflows.views.get_shutdown_manager")
    def test_tracks_request_lifecycle(
        self,
        mock_get_manager,
        mock_verify,
    ):
        """Test that webhook tracks request start and end."""
        mock_verify.return_value = True

        mock_manager = MagicMock()
        mock_manager.is_shutting_down = False
        mock_get_manager.return_value = mock_manager

        @workflow(workflow_id="test-track-wf")
        def test_workflow(ctx):
            return "result"

        payload = {
            "workflow_id": "test-track-wf",
            "run_id": "test-run",
            "data": {},
            "completed_steps": {},
        }

        request = self.factory.post(
            "/hookflow/workflow/test-track-wf/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        response = workflow_webhook_raw(request, workflow_id="test-track-wf")

        self.assertEqual(response.status_code, 200)
        # Verify tracking methods were called
        mock_manager.track_request_start.assert_called_once_with("test-run")
        mock_manager.track_request_end.assert_called_once_with("test-run")


if __name__ == "__main__":
    unittest.main()
