from __future__ import annotations

import json
import time
import unittest
from unittest.mock import patch

from django.test import RequestFactory
from django.test import override_settings

from django_hookflow import workflow
from django_hookflow.exceptions import ExecutionTimeoutError
from django_hookflow.workflows.registry import _workflow_registry
from django_hookflow.workflows.views import DEFAULT_EXECUTION_TIMEOUT
from django_hookflow.workflows.views import _execution_timeout
from django_hookflow.workflows.views import _get_execution_timeout
from django_hookflow.workflows.views import _TimeoutFlag
from django_hookflow.workflows.views import workflow_webhook_raw


class TestTimeoutFlag(unittest.TestCase):
    """Tests for the _TimeoutFlag helper class."""

    def test_initial_state_is_not_timed_out(self):
        """Test that flag starts in not-timed-out state."""
        flag = _TimeoutFlag()
        self.assertFalse(flag.is_timed_out())

    def test_set_timed_out_changes_state(self):
        """Test that set_timed_out() changes the flag state."""
        flag = _TimeoutFlag()
        flag.set_timed_out()
        self.assertTrue(flag.is_timed_out())


class TestExecutionTimeoutContextManager(unittest.TestCase):
    """Tests for the _execution_timeout context manager."""

    def test_normal_execution_completes(self):
        """Test that normal execution completes without error."""
        with _execution_timeout(10, "test-workflow", "test-run") as flag:
            # Quick operation
            result = 1 + 1
            self.assertFalse(flag.is_timed_out())

        self.assertEqual(result, 2)

    def test_timeout_flag_is_set_after_timeout(self):
        """Test that timeout flag is set after timeout expires."""
        flag_captured = None
        try:
            with _execution_timeout(1, "test-workflow", "test-run") as flag:
                flag_captured = flag
                # Wait for timeout
                time.sleep(1.5)
                self.assertTrue(flag.is_timed_out())
        except ExecutionTimeoutError:
            # Expected - verify flag was set
            self.assertTrue(flag_captured.is_timed_out())

    def test_raises_error_if_timed_out_on_exit(self):
        """Test that ExecutionTimeoutError is raised on context exit."""
        with self.assertRaises(ExecutionTimeoutError) as ctx:
            with _execution_timeout(1, "test-workflow", "test-run"):
                time.sleep(1.5)

        self.assertEqual(ctx.exception.timeout_seconds, 1)
        self.assertEqual(ctx.exception.workflow_id, "test-workflow")
        self.assertEqual(ctx.exception.run_id, "test-run")

    def test_zero_timeout_disables_timer(self):
        """Test that timeout of 0 disables the timer."""
        with _execution_timeout(0, "test-workflow", "test-run") as flag:
            time.sleep(0.1)
            self.assertFalse(flag.is_timed_out())


class TestGetExecutionTimeout(unittest.TestCase):
    """Tests for the _get_execution_timeout function."""

    def test_returns_default_when_not_configured(self):
        """Test that default timeout is returned when not configured."""
        timeout = _get_execution_timeout()
        self.assertEqual(timeout, DEFAULT_EXECUTION_TIMEOUT)

    @override_settings(DJANGO_HOOKFLOW_EXECUTION_TIMEOUT=60)
    def test_returns_configured_value(self):
        """Test that configured timeout is returned."""
        timeout = _get_execution_timeout()
        self.assertEqual(timeout, 60)


class TestExecutionTimeoutError(unittest.TestCase):
    """Tests for the ExecutionTimeoutError exception."""

    def test_stores_timeout_info(self):
        """Test that exception stores timeout information."""
        error = ExecutionTimeoutError(
            "Test timeout",
            timeout_seconds=30,
            workflow_id="my-workflow",
            run_id="my-run",
        )

        self.assertEqual(error.timeout_seconds, 30)
        self.assertEqual(error.workflow_id, "my-workflow")
        self.assertEqual(error.run_id, "my-run")
        self.assertIn("Test timeout", str(error))


class TestWorkflowDecoratorTimeout(unittest.TestCase):
    """Tests for per-workflow timeout configuration."""

    def setUp(self):
        _workflow_registry.clear()

    def test_workflow_without_timeout_has_none(self):
        """Test that workflow without timeout parameter has None."""

        @workflow
        def test_workflow(ctx):
            return "result"

        self.assertIsNone(test_workflow.timeout)

    def test_workflow_with_timeout_parameter(self):
        """Test that workflow timeout parameter is stored."""

        @workflow(timeout=60)
        def test_workflow(ctx):
            return "result"

        self.assertEqual(test_workflow.timeout, 60)

    def test_workflow_timeout_zero_disables_timeout(self):
        """Test that timeout=0 can be used to disable timeout."""

        @workflow(timeout=0)
        def test_workflow(ctx):
            return "result"

        self.assertEqual(test_workflow.timeout, 0)


class TestWorkflowWebhookTimeout(unittest.TestCase):
    """Tests for timeout handling in workflow webhook."""

    def setUp(self):
        _workflow_registry.clear()
        self.factory = RequestFactory()

    @override_settings(
        DJANGO_HOOKFLOW_RATE_LIMIT=None,
        DJANGO_HOOKFLOW_EXECUTION_TIMEOUT=1,
    )
    @patch("django_hookflow.workflows.views.verify_qstash_signature")
    @patch("django_hookflow.workflows.views._publish_with_retry")
    @patch("django_hookflow.dlq.DeadLetterEntry.add_entry")
    def test_timeout_triggers_retry(
        self,
        mock_dlq,
        mock_publish,
        mock_verify,
    ):
        """Test that timeout triggers retry scheduling."""
        mock_verify.return_value = True
        mock_publish.return_value = True

        @workflow(workflow_id="slow-workflow", timeout=1)
        def slow_workflow(ctx):
            time.sleep(2)  # Exceed timeout
            return "result"

        payload = {
            "workflow_id": "slow-workflow",
            "run_id": "test-run",
            "data": {},
            "completed_steps": {},
            "attempt": 0,
        }

        request = self.factory.post(
            "/hookflow/workflow/slow-workflow/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        response = workflow_webhook_raw(request, workflow_id="slow-workflow")

        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertEqual(response_data["status"], "retrying")
        self.assertEqual(response_data["reason"], "execution_timeout")
        mock_publish.assert_called_once()

    @override_settings(
        DJANGO_HOOKFLOW_RATE_LIMIT=None,
        DJANGO_HOOKFLOW_EXECUTION_TIMEOUT=1,
    )
    @patch("django_hookflow.workflows.views.verify_qstash_signature")
    @patch("django_hookflow.workflows.views._publish_with_retry")
    @patch("django_hookflow.dlq.DeadLetterEntry.add_entry")
    @patch("django_hookflow.retry.should_retry")
    def test_timeout_adds_to_dlq_when_no_retries(
        self,
        mock_should_retry,
        mock_dlq,
        mock_publish,
        mock_verify,
    ):
        """Test that timeout adds to DLQ when retries exhausted."""
        mock_verify.return_value = True
        mock_publish.return_value = True
        mock_should_retry.return_value = False

        @workflow(workflow_id="slow-workflow-dlq", timeout=1)
        def slow_workflow(ctx):
            time.sleep(2)
            return "result"

        payload = {
            "workflow_id": "slow-workflow-dlq",
            "run_id": "test-run",
            "data": {},
            "completed_steps": {},
            "attempt": 3,
        }

        request = self.factory.post(
            "/hookflow/workflow/slow-workflow-dlq/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        response = workflow_webhook_raw(
            request, workflow_id="slow-workflow-dlq"
        )

        self.assertEqual(response.status_code, 504)
        response_data = json.loads(response.content)
        self.assertTrue(response_data["added_to_dlq"])
        mock_dlq.assert_called_once()

    @override_settings(
        DJANGO_HOOKFLOW_RATE_LIMIT=None,
        DJANGO_HOOKFLOW_EXECUTION_TIMEOUT=60,
    )
    @patch("django_hookflow.workflows.views.verify_qstash_signature")
    def test_per_workflow_timeout_overrides_global(self, mock_verify):
        """Test that per-workflow timeout takes precedence."""
        mock_verify.return_value = True

        @workflow(workflow_id="custom-timeout-wf", timeout=0)
        def fast_workflow(ctx):
            return "result"

        payload = {
            "workflow_id": "custom-timeout-wf",
            "run_id": "test-run",
            "data": {},
            "completed_steps": {},
        }

        request = self.factory.post(
            "/hookflow/workflow/custom-timeout-wf/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        response = workflow_webhook_raw(
            request, workflow_id="custom-timeout-wf"
        )

        # Should complete normally (timeout=0 disables it)
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertEqual(response_data["status"], "completed")


class TestDefaultExecutionTimeoutConstant(unittest.TestCase):
    """Tests for default execution timeout constant."""

    def test_default_execution_timeout_is_30_seconds(self):
        """Verify the default execution timeout is 30 seconds."""
        self.assertEqual(DEFAULT_EXECUTION_TIMEOUT, 30)


if __name__ == "__main__":
    unittest.main()
