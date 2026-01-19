from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from django.test import RequestFactory

from django_hookflow import workflow
from django_hookflow.exceptions import StepCompleted
from django_hookflow.exceptions import WorkflowError
from django_hookflow.workflows import StepManager
from django_hookflow.workflows import get_all_workflows
from django_hookflow.workflows import get_workflow
from django_hookflow.workflows.context import WorkflowContext as ContextClass
from django_hookflow.workflows.registry import _workflow_registry
from django_hookflow.workflows.registry import generate_workflow_id


class TestWorkflowRegistry(unittest.TestCase):
    def setUp(self):
        # Clear the registry before each test
        _workflow_registry.clear()

    def test_generate_workflow_id(self):
        def my_func():
            pass

        workflow_id = generate_workflow_id(my_func)
        self.assertIn("my_func", workflow_id)
        self.assertIn("test_workflows", workflow_id)

    def test_workflow_decorator_registers_workflow(self):
        @workflow
        def test_workflow(ctx):
            return "result"

        self.assertIn(test_workflow.workflow_id, _workflow_registry)
        wf = get_workflow(test_workflow.workflow_id)
        self.assertEqual(wf, test_workflow)

    def test_workflow_decorator_with_custom_id(self):
        @workflow(workflow_id="custom-workflow-id")
        def test_workflow(ctx):
            return "result"

        self.assertEqual(test_workflow.workflow_id, "custom-workflow-id")
        self.assertIn("custom-workflow-id", _workflow_registry)

    def test_get_all_workflows(self):
        @workflow
        def workflow_a(ctx):
            pass

        @workflow
        def workflow_b(ctx):
            pass

        all_workflows = get_all_workflows()
        self.assertEqual(len(all_workflows), 2)

    def test_duplicate_workflow_id_raises_error(self):
        @workflow(workflow_id="duplicate-id")
        def workflow_a(ctx):
            pass

        with self.assertRaises(ValueError) as context:

            @workflow(workflow_id="duplicate-id")
            def workflow_b(ctx):
                pass

        self.assertIn("already registered", str(context.exception))


class TestStepManager(unittest.TestCase):
    def test_run_returns_cached_result(self):
        completed_steps = {"step-1": "cached_result"}
        manager = StepManager(
            completed_steps=completed_steps,
            run_id="test-run",
            workflow_id="test-workflow",
        )

        result = manager.run("step-1", lambda: "new_result")
        self.assertEqual(result, "cached_result")

    def test_run_executes_and_raises_step_completed(self):
        manager = StepManager(
            completed_steps={},
            run_id="test-run",
            workflow_id="test-workflow",
        )

        with self.assertRaises(StepCompleted) as context:
            manager.run("step-1", lambda: "new_result")

        self.assertEqual(context.exception.step_id, "step-1")
        self.assertEqual(context.exception.result, "new_result")
        expected = {"step-1": "new_result"}
        self.assertEqual(context.exception.completed_steps, expected)

    def test_run_with_args_and_kwargs(self):
        manager = StepManager(
            completed_steps={},
            run_id="test-run",
            workflow_id="test-workflow",
        )

        def add(a, b, multiplier=1):
            return (a + b) * multiplier

        with self.assertRaises(StepCompleted) as context:
            manager.run("step-1", add, 2, 3, multiplier=2)

        self.assertEqual(context.exception.result, 10)

    def test_run_wraps_exceptions_in_workflow_error(self):
        manager = StepManager(
            completed_steps={},
            run_id="test-run",
            workflow_id="test-workflow",
        )

        def failing_function():
            raise ValueError("Something went wrong")

        with self.assertRaises(WorkflowError) as context:
            manager.run("step-1", failing_function)

        self.assertIn("step-1", str(context.exception))
        self.assertIn("Something went wrong", str(context.exception))

    def test_sleep_returns_if_already_completed(self):
        completed_steps = {"sleep-1": {"slept_for": 60}}
        manager = StepManager(
            completed_steps=completed_steps,
            run_id="test-run",
            workflow_id="test-workflow",
        )

        # Should return without raising
        result = manager.sleep("sleep-1", 60)
        self.assertIsNone(result)

    def test_sleep_raises_step_completed(self):
        manager = StepManager(
            completed_steps={},
            run_id="test-run",
            workflow_id="test-workflow",
        )

        with self.assertRaises(StepCompleted) as context:
            manager.sleep("sleep-1", 60)

        self.assertEqual(context.exception.step_id, "sleep-1")
        self.assertIn("slept_for", context.exception.result)
        self.assertEqual(context.exception.result["slept_for"], 60)


class TestWorkflowContext(unittest.TestCase):
    def test_context_properties(self):
        step_manager = StepManager(
            completed_steps={},
            run_id="test-run",
            workflow_id="test-workflow",
        )
        ctx = ContextClass(
            data={"key": "value"},
            step=step_manager,
            run_id="test-run",
            workflow_id="test-workflow",
        )

        self.assertEqual(ctx.data, {"key": "value"})
        self.assertEqual(ctx.run_id, "test-run")
        self.assertEqual(ctx.workflow_id, "test-workflow")
        self.assertIs(ctx.step, step_manager)


class TestWorkflowWrapper(unittest.TestCase):
    def setUp(self):
        _workflow_registry.clear()

    @patch("django_hookflow.workflows.decorator.get_qstash_client")
    def test_trigger_returns_run_id(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        @workflow
        def test_workflow(ctx):
            return "result"

        run_id = test_workflow.trigger(data={"key": "value"})

        self.assertIsNotNone(run_id)
        mock_client.publish_json.assert_called_once()

    @patch("django_hookflow.workflows.decorator.get_qstash_client")
    def test_trigger_with_custom_run_id(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        @workflow
        def test_workflow(ctx):
            return "result"

        run_id = test_workflow.trigger(data={}, run_id="custom-run-id")

        self.assertEqual(run_id, "custom-run-id")

    @patch("django_hookflow.workflows.decorator.get_qstash_client")
    def test_trigger_builds_correct_webhook_url(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        @workflow(workflow_id="my-workflow")
        def test_workflow(ctx):
            return "result"

        test_workflow.trigger(data={})

        call_kwargs = mock_client.publish_json.call_args
        url = call_kwargs.kwargs["url"]
        self.assertIn("/hookflow/workflow/my-workflow/", url)

    def test_execute_runs_workflow_function(self):
        @workflow
        def test_workflow(ctx):
            return ctx.data.get("value", "default")

        result = test_workflow.execute(
            data={"value": "test"},
            run_id="test-run",
            completed_steps={},
        )

        # This should complete since there are no steps
        self.assertEqual(result, "test")

    def test_execute_with_completed_steps(self):
        @workflow
        def test_workflow(ctx):
            step1 = ctx.step.run("step-1", lambda: "first")
            return step1

        result = test_workflow.execute(
            data={},
            run_id="test-run",
            completed_steps={"step-1": "cached_first"},
        )

        self.assertEqual(result, "cached_first")


class TestWorkflowView(unittest.TestCase):
    def setUp(self):
        _workflow_registry.clear()
        self.factory = RequestFactory()

    @patch("django_hookflow.workflows.views.verify_qstash_signature")
    @patch("django_hookflow.workflows.views.publish_next_step")
    def test_webhook_handles_step_completion(self, mock_publish, mock_verify):
        from django_hookflow.workflows.views import workflow_webhook

        mock_verify.return_value = True

        @workflow(workflow_id="test-workflow")
        def test_workflow(ctx):
            result = ctx.step.run("step-1", lambda: "step_result")
            return result

        payload = {
            "workflow_id": "test-workflow",
            "run_id": "test-run",
            "data": {},
            "completed_steps": {},
        }

        request = self.factory.post(
            "/hookflow/workflow/test-workflow/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        response = workflow_webhook(request, "test-workflow")

        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertEqual(response_data["status"], "step_completed")
        mock_publish.assert_called_once()

    @patch("django_hookflow.workflows.views.verify_qstash_signature")
    def test_webhook_handles_workflow_completion(self, mock_verify):
        from django_hookflow.workflows.views import workflow_webhook

        mock_verify.return_value = True

        @workflow(workflow_id="complete-workflow")
        def test_workflow(ctx):
            return "final_result"

        payload = {
            "workflow_id": "complete-workflow",
            "run_id": "test-run",
            "data": {},
            "completed_steps": {},
        }

        request = self.factory.post(
            "/hookflow/workflow/complete-workflow/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        response = workflow_webhook(request, "complete-workflow")

        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertEqual(response_data["status"], "completed")
        self.assertEqual(response_data["result"], "final_result")

    @patch("django_hookflow.workflows.views.verify_qstash_signature")
    def test_webhook_returns_404_for_unknown_workflow(self, mock_verify):
        from django_hookflow.workflows.views import workflow_webhook

        mock_verify.return_value = True

        payload = {
            "workflow_id": "unknown-workflow",
            "run_id": "test-run",
            "data": {},
            "completed_steps": {},
        }

        request = self.factory.post(
            "/hookflow/workflow/unknown-workflow/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        response = workflow_webhook(request, "unknown-workflow")

        self.assertEqual(response.status_code, 404)


class TestExceptions(unittest.TestCase):
    def test_workflow_error_inherits_from_hookflow_exception(self):
        from django_hookflow.exceptions import HookFlowException

        error = WorkflowError("test error")
        self.assertIsInstance(error, HookFlowException)

    def test_step_completed_stores_data(self):
        exc = StepCompleted(
            step_id="test-step",
            result={"data": "value"},
            completed_steps={"test-step": {"data": "value"}},
        )

        self.assertEqual(exc.step_id, "test-step")
        self.assertEqual(exc.result, {"data": "value"})
        self.assertEqual(exc.completed_steps, {"test-step": {"data": "value"}})


if __name__ == "__main__":
    unittest.main()
