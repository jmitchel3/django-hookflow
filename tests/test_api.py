from __future__ import annotations

import json
import unittest
from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

from django.test import RequestFactory

from django_hookflow import workflow
from django_hookflow.api.views import serialize_workflow_run
from django_hookflow.api.views import workflow_list
from django_hookflow.api.views import workflow_status
from django_hookflow.api.views import workflow_types
from django_hookflow.workflows.registry import _workflow_registry


class TestWorkflowStatusAPI(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        _workflow_registry.clear()

    @patch("django_hookflow.api.views.WorkflowRun")
    def test_workflow_status_returns_correct_data(self, mock_model):
        """Test that workflow_status returns correct workflow data."""
        mock_run = MagicMock()
        mock_run.run_id = "test-run-123"
        mock_run.workflow_id = "test-workflow"
        mock_run.status = "completed"
        mock_run.data = {"key": "value"}
        mock_run.result = {"output": "result"}
        mock_run.error_message = None
        mock_run.created_at = datetime(
            2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc
        )
        mock_run.updated_at = datetime(
            2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc
        )
        mock_run.completed_at = datetime(
            2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc
        )
        mock_run.step_executions.all.return_value.order_by.return_value = []

        mock_queryset = MagicMock()
        mock_queryset.get.return_value = mock_run
        mock_model.objects.prefetch_related.return_value = mock_queryset

        request = self.factory.get("/api/workflows/test-run-123/")
        response = workflow_status(request, "test-run-123")

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["run_id"], "test-run-123")
        self.assertEqual(data["workflow_id"], "test-workflow")
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["data"], {"key": "value"})
        self.assertEqual(data["result"], {"output": "result"})
        self.assertIsNone(data["error_message"])
        self.assertEqual(data["steps"], [])

    @patch("django_hookflow.api.views.WorkflowRun")
    def test_workflow_status_returns_404_for_unknown_run_id(self, mock_model):
        """Test that workflow_status returns 404 for unknown run_id."""
        # Create a proper exception class for the mock
        mock_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_queryset = MagicMock()
        mock_queryset.get.side_effect = mock_model.DoesNotExist()
        mock_model.objects.prefetch_related.return_value = mock_queryset

        request = self.factory.get("/api/workflows/unknown-run/")
        response = workflow_status(request, "unknown-run")

        self.assertEqual(response.status_code, 404)
        data = json.loads(response.content)
        self.assertEqual(data["error"], "Workflow run not found")

    @patch("django_hookflow.api.views.WorkflowRun")
    def test_workflow_status_includes_steps(self, mock_model):
        """Test that workflow_status includes step information."""
        mock_step = MagicMock()
        mock_step.step_id = "step-1"
        mock_step.result = {"step_output": "data"}
        mock_step.executed_at = datetime(
            2024, 1, 1, 12, 0, 30, tzinfo=timezone.utc
        )

        mock_run = MagicMock()
        mock_run.run_id = "test-run-123"
        mock_run.workflow_id = "test-workflow"
        mock_run.status = "completed"
        mock_run.data = {}
        mock_run.result = None
        mock_run.error_message = None
        mock_run.created_at = datetime(
            2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc
        )
        mock_run.updated_at = datetime(
            2024, 1, 1, 12, 0, 30, tzinfo=timezone.utc
        )
        mock_run.completed_at = datetime(
            2024, 1, 1, 12, 0, 30, tzinfo=timezone.utc
        )
        mock_run.step_executions.all.return_value.order_by.return_value = [
            mock_step
        ]

        mock_queryset = MagicMock()
        mock_queryset.get.return_value = mock_run
        mock_model.objects.prefetch_related.return_value = mock_queryset

        request = self.factory.get("/api/workflows/test-run-123/")
        response = workflow_status(request, "test-run-123")

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(len(data["steps"]), 1)
        self.assertEqual(data["steps"][0]["step_id"], "step-1")
        self.assertEqual(data["steps"][0]["result"], {"step_output": "data"})


class TestWorkflowListAPI(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("django_hookflow.api.views.WorkflowRun")
    def test_workflow_list_with_no_filters(self, mock_model):
        """Test workflow_list returns all runs without filters."""
        mock_run = MagicMock()
        mock_run.run_id = "test-run-1"
        mock_run.workflow_id = "test-workflow"
        mock_run.status = "completed"
        mock_run.data = {}
        mock_run.result = None
        mock_run.error_message = None
        mock_run.created_at = datetime(
            2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc
        )
        mock_run.updated_at = datetime(
            2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc
        )
        mock_run.completed_at = None
        mock_run.step_executions.all.return_value.order_by.return_value = []

        mock_queryset = MagicMock()
        mock_queryset.filter.return_value = mock_queryset
        mock_queryset.count.return_value = 1
        mock_queryset.order_by.return_value.__getitem__.return_value = [
            mock_run
        ]
        mock_model.objects.prefetch_related.return_value = mock_queryset

        request = self.factory.get("/api/workflows/")
        response = workflow_list(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["limit"], 50)
        self.assertEqual(data["offset"], 0)
        self.assertEqual(len(data["runs"]), 1)

    @patch("django_hookflow.api.views.WorkflowRun")
    def test_workflow_list_with_workflow_id_filter(self, mock_model):
        """Test workflow_list filters by workflow_id."""
        mock_queryset = MagicMock()
        mock_queryset.filter.return_value = mock_queryset
        mock_queryset.count.return_value = 0
        mock_queryset.order_by.return_value.__getitem__.return_value = []
        mock_model.objects.prefetch_related.return_value = mock_queryset

        request = self.factory.get("/api/workflows/?workflow_id=my-workflow")
        response = workflow_list(request)

        self.assertEqual(response.status_code, 200)
        mock_queryset.filter.assert_any_call(workflow_id="my-workflow")

    @patch("django_hookflow.api.views.WorkflowRun")
    def test_workflow_list_with_status_filter(self, mock_model):
        """Test workflow_list filters by status."""
        mock_queryset = MagicMock()
        mock_queryset.filter.return_value = mock_queryset
        mock_queryset.count.return_value = 0
        mock_queryset.order_by.return_value.__getitem__.return_value = []
        mock_model.objects.prefetch_related.return_value = mock_queryset

        request = self.factory.get("/api/workflows/?status=running")
        response = workflow_list(request)

        self.assertEqual(response.status_code, 200)
        mock_queryset.filter.assert_any_call(status="running")

    @patch("django_hookflow.api.views.WorkflowRun")
    def test_workflow_list_pagination(self, mock_model):
        """Test workflow_list handles pagination correctly."""
        mock_queryset = MagicMock()
        mock_queryset.filter.return_value = mock_queryset
        mock_queryset.count.return_value = 100
        mock_queryset.order_by.return_value.__getitem__.return_value = []
        mock_model.objects.prefetch_related.return_value = mock_queryset

        request = self.factory.get("/api/workflows/?limit=10&offset=20")
        response = workflow_list(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["total"], 100)
        self.assertEqual(data["limit"], 10)
        self.assertEqual(data["offset"], 20)

    @patch("django_hookflow.api.views.WorkflowRun")
    def test_workflow_list_invalid_pagination_uses_defaults(self, mock_model):
        """Test workflow_list uses defaults for invalid pagination values."""
        mock_queryset = MagicMock()
        mock_queryset.filter.return_value = mock_queryset
        mock_queryset.count.return_value = 0
        mock_queryset.order_by.return_value.__getitem__.return_value = []
        mock_model.objects.prefetch_related.return_value = mock_queryset

        request = self.factory.get(
            "/api/workflows/?limit=invalid&offset=invalid"
        )
        response = workflow_list(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["limit"], 50)
        self.assertEqual(data["offset"], 0)


class TestWorkflowTypesAPI(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        _workflow_registry.clear()

    def test_workflow_types_returns_empty_list_when_no_workflows(self):
        """Test workflow_types returns empty list when none registered."""
        request = self.factory.get("/api/workflows/types/")
        response = workflow_types(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["workflows"], [])
        self.assertEqual(data["count"], 0)

    def test_workflow_types_returns_registered_workflows(self):
        """Test workflow_types returns all registered workflow IDs."""

        @workflow(workflow_id="workflow-a")
        def workflow_a(ctx):
            pass

        @workflow(workflow_id="workflow-b")
        def workflow_b(ctx):
            pass

        request = self.factory.get("/api/workflows/types/")
        response = workflow_types(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["count"], 2)
        self.assertIn("workflow-a", data["workflows"])
        self.assertIn("workflow-b", data["workflows"])


class TestSerializeWorkflowRun(unittest.TestCase):
    def test_serialize_workflow_run_with_all_fields(self):
        """Test serialization includes all fields correctly."""
        mock_step = MagicMock()
        mock_step.step_id = "step-1"
        mock_step.result = {"data": "value"}
        mock_step.executed_at = datetime(
            2024, 1, 1, 12, 0, 30, tzinfo=timezone.utc
        )

        mock_run = MagicMock()
        mock_run.run_id = "run-123"
        mock_run.workflow_id = "my-workflow"
        mock_run.status = "completed"
        mock_run.data = {"input": "data"}
        mock_run.result = {"output": "result"}
        mock_run.error_message = None
        mock_run.created_at = datetime(
            2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc
        )
        mock_run.updated_at = datetime(
            2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc
        )
        mock_run.completed_at = datetime(
            2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc
        )
        mock_run.step_executions.all.return_value.order_by.return_value = [
            mock_step
        ]

        result = serialize_workflow_run(mock_run)

        self.assertEqual(result["run_id"], "run-123")
        self.assertEqual(result["workflow_id"], "my-workflow")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["data"], {"input": "data"})
        self.assertEqual(result["result"], {"output": "result"})
        self.assertIsNone(result["error_message"])
        self.assertEqual(result["created_at"], "2024-01-01T12:00:00+00:00")
        self.assertEqual(result["updated_at"], "2024-01-01T12:01:00+00:00")
        self.assertEqual(result["completed_at"], "2024-01-01T12:01:00+00:00")
        self.assertEqual(len(result["steps"]), 1)
        self.assertEqual(result["steps"][0]["step_id"], "step-1")

    def test_serialize_workflow_run_with_null_timestamps(self):
        """Test serialization handles null timestamps."""
        mock_run = MagicMock()
        mock_run.run_id = "run-123"
        mock_run.workflow_id = "my-workflow"
        mock_run.status = "pending"
        mock_run.data = {}
        mock_run.result = None
        mock_run.error_message = None
        mock_run.created_at = None
        mock_run.updated_at = None
        mock_run.completed_at = None
        mock_run.step_executions.all.return_value.order_by.return_value = []

        result = serialize_workflow_run(mock_run)

        self.assertIsNone(result["created_at"])
        self.assertIsNone(result["updated_at"])
        self.assertIsNone(result["completed_at"])

    def test_serialize_workflow_run_with_error(self):
        """Test serialization includes error message."""
        mock_run = MagicMock()
        mock_run.run_id = "run-123"
        mock_run.workflow_id = "my-workflow"
        mock_run.status = "failed"
        mock_run.data = {}
        mock_run.result = None
        mock_run.error_message = "Something went wrong"
        mock_run.created_at = datetime(
            2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc
        )
        mock_run.updated_at = datetime(
            2024, 1, 1, 12, 0, 30, tzinfo=timezone.utc
        )
        mock_run.completed_at = None
        mock_run.step_executions.all.return_value.order_by.return_value = []

        result = serialize_workflow_run(mock_run)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_message"], "Something went wrong")


if __name__ == "__main__":
    unittest.main()
