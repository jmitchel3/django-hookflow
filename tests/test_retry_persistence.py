from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from django.test import RequestFactory
from django.test import TestCase
from django.test import override_settings

from django_hookflow import workflow
from django_hookflow.models import WorkflowRun
from django_hookflow.models import WorkflowRunStatus
from django_hookflow.persistence import WorkflowPersistence
from django_hookflow.workflows.registry import _workflow_registry
from django_hookflow.workflows.views import DEFAULT_MAX_PUBLISH_FAILURES
from django_hookflow.workflows.views import _get_max_publish_failures
from django_hookflow.workflows.views import _publish_with_retry
from django_hookflow.workflows.views import workflow_webhook_raw


class TestWorkflowRunRetryAttempt(TestCase):
    """Tests for the retry_attempt field on WorkflowRun model."""

    def test_default_retry_attempt_is_zero(self):
        """Test that retry_attempt defaults to 0."""
        run = WorkflowRun.objects.create(
            run_id="test-run",
            workflow_id="test-workflow",
            status=WorkflowRunStatus.PENDING,
        )
        self.assertEqual(run.retry_attempt, 0)

    def test_retry_attempt_can_be_set(self):
        """Test that retry_attempt can be set and retrieved."""
        run = WorkflowRun.objects.create(
            run_id="test-run",
            workflow_id="test-workflow",
            status=WorkflowRunStatus.PENDING,
            retry_attempt=5,
        )
        self.assertEqual(run.retry_attempt, 5)


class TestIncrementRetryAttempt(TestCase):
    """Tests for WorkflowPersistence.increment_retry_attempt()."""

    def test_increment_retry_attempt(self):
        """Test that increment_retry_attempt increments the counter."""
        WorkflowRun.objects.create(
            run_id="test-run",
            workflow_id="test-workflow",
            status=WorkflowRunStatus.RUNNING,
            retry_attempt=2,
        )

        result = WorkflowPersistence.increment_retry_attempt("test-run")

        self.assertEqual(result, 3)
        run = WorkflowRun.objects.get(run_id="test-run")
        self.assertEqual(run.retry_attempt, 3)

    def test_increment_retry_attempt_from_zero(self):
        """Test incrementing from zero."""
        WorkflowRun.objects.create(
            run_id="test-run",
            workflow_id="test-workflow",
            status=WorkflowRunStatus.RUNNING,
        )

        result = WorkflowPersistence.increment_retry_attempt("test-run")

        self.assertEqual(result, 1)

    def test_increment_retry_attempt_not_found(self):
        """Test that None is returned for non-existent run."""
        result = WorkflowPersistence.increment_retry_attempt("nonexistent")
        self.assertIsNone(result)


class TestResetRetryAttempt(TestCase):
    """Tests for WorkflowPersistence.reset_retry_attempt()."""

    def test_reset_retry_attempt(self):
        """Test that reset_retry_attempt resets to zero."""
        WorkflowRun.objects.create(
            run_id="test-run",
            workflow_id="test-workflow",
            status=WorkflowRunStatus.RUNNING,
            retry_attempt=5,
        )

        result = WorkflowPersistence.reset_retry_attempt("test-run")

        self.assertTrue(result)
        run = WorkflowRun.objects.get(run_id="test-run")
        self.assertEqual(run.retry_attempt, 0)

    def test_reset_retry_attempt_already_zero(self):
        """Test resetting when already zero."""
        WorkflowRun.objects.create(
            run_id="test-run",
            workflow_id="test-workflow",
            status=WorkflowRunStatus.RUNNING,
            retry_attempt=0,
        )

        result = WorkflowPersistence.reset_retry_attempt("test-run")

        self.assertTrue(result)
        run = WorkflowRun.objects.get(run_id="test-run")
        self.assertEqual(run.retry_attempt, 0)

    def test_reset_retry_attempt_not_found(self):
        """Test that False is returned for non-existent run."""
        result = WorkflowPersistence.reset_retry_attempt("nonexistent")
        self.assertFalse(result)


class TestGetMaxPublishFailures(unittest.TestCase):
    """Tests for _get_max_publish_failures function."""

    def test_returns_default_when_not_configured(self):
        """Test that default is returned when not configured."""
        max_failures = _get_max_publish_failures()
        self.assertEqual(max_failures, DEFAULT_MAX_PUBLISH_FAILURES)

    @override_settings(DJANGO_HOOKFLOW_MAX_PUBLISH_FAILURES=5)
    def test_returns_configured_value(self):
        """Test that configured value is returned."""
        max_failures = _get_max_publish_failures()
        self.assertEqual(max_failures, 5)


class TestPublishWithRetry(unittest.TestCase):
    """Tests for _publish_with_retry function."""

    @patch("django_hookflow.workflows.views.publish_next_step")
    def test_success_on_first_attempt(self, mock_publish):
        """Test successful publish on first attempt."""
        mock_publish.return_value = None

        result = _publish_with_retry(
            workflow_id="test-wf",
            run_id="test-run",
            data={},
            completed_steps={},
        )

        self.assertTrue(result)
        mock_publish.assert_called_once()

    @override_settings(DJANGO_HOOKFLOW_MAX_PUBLISH_FAILURES=3)
    @patch("django_hookflow.workflows.views.publish_next_step")
    @patch("django_hookflow.workflows.views.time.sleep")
    def test_retries_on_failure(self, mock_sleep, mock_publish):
        """Test that publish retries on failure."""
        mock_publish.side_effect = [
            Exception("First fail"),
            Exception("Second fail"),
            None,  # Third attempt succeeds
        ]

        result = _publish_with_retry(
            workflow_id="test-wf",
            run_id="test-run",
            data={},
            completed_steps={},
        )

        self.assertTrue(result)
        self.assertEqual(mock_publish.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @override_settings(DJANGO_HOOKFLOW_MAX_PUBLISH_FAILURES=3)
    @patch("django_hookflow.workflows.views.publish_next_step")
    @patch("django_hookflow.workflows.views.time.sleep")
    def test_returns_false_after_all_retries_fail(
        self, mock_sleep, mock_publish
    ):
        """Test that False is returned when all retries fail."""
        mock_publish.side_effect = Exception("Always fails")

        result = _publish_with_retry(
            workflow_id="test-wf",
            run_id="test-run",
            data={},
            completed_steps={},
        )

        self.assertFalse(result)
        self.assertEqual(mock_publish.call_count, 3)

    @override_settings(DJANGO_HOOKFLOW_MAX_PUBLISH_FAILURES=3)
    @patch("django_hookflow.workflows.views.publish_next_step")
    @patch("django_hookflow.workflows.views.time.sleep")
    def test_exponential_backoff(self, mock_sleep, mock_publish):
        """Test that exponential backoff is used between retries."""
        mock_publish.side_effect = [
            Exception("First fail"),
            Exception("Second fail"),
            None,
        ]

        _publish_with_retry(
            workflow_id="test-wf",
            run_id="test-run",
            data={},
            completed_steps={},
        )

        # Check backoff delays: 0.1s, 0.2s
        self.assertEqual(mock_sleep.call_count, 2)
        calls = mock_sleep.call_args_list
        self.assertAlmostEqual(calls[0][0][0], 0.1, places=1)
        self.assertAlmostEqual(calls[1][0][0], 0.2, places=1)


class TestDefaultMaxPublishFailuresConstant(unittest.TestCase):
    """Tests for default max publish failures constant."""

    def test_default_is_3(self):
        """Verify the default max publish failures is 3."""
        self.assertEqual(DEFAULT_MAX_PUBLISH_FAILURES, 3)


class TestWorkflowWebhookRetryPersistence(TestCase):
    """Tests for retry persistence in workflow webhook."""

    def setUp(self):
        _workflow_registry.clear()
        self.factory = RequestFactory()

    @override_settings(
        DJANGO_HOOKFLOW_RATE_LIMIT=None,
        DJANGO_HOOKFLOW_PERSISTENCE_ENABLED=True,
    )
    @patch("django_hookflow.workflows.views.verify_qstash_signature")
    @patch("django_hookflow.workflows.views._publish_with_retry")
    def test_reset_retry_on_step_completion(
        self,
        mock_publish,
        mock_verify,
    ):
        """Test that retry counter is reset on step completion."""
        mock_verify.return_value = True
        mock_publish.return_value = True

        # Create a workflow run with retry_attempt > 0
        WorkflowRun.objects.create(
            run_id="test-run",
            workflow_id="step-complete-wf",
            status=WorkflowRunStatus.RUNNING,
            retry_attempt=3,
        )

        @workflow(workflow_id="step-complete-wf")
        def test_workflow(ctx):
            result = ctx.step.run("step-1", lambda: "done")
            return result

        payload = {
            "workflow_id": "step-complete-wf",
            "run_id": "test-run",
            "data": {},
            "completed_steps": {},
        }

        request = self.factory.post(
            "/hookflow/workflow/step-complete-wf/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        response = workflow_webhook_raw(
            request, workflow_id="step-complete-wf"
        )

        self.assertEqual(response.status_code, 200)
        # Verify retry was reset
        run = WorkflowRun.objects.get(run_id="test-run")
        self.assertEqual(run.retry_attempt, 0)


if __name__ == "__main__":
    unittest.main()
