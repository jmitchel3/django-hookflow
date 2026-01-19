from __future__ import annotations

from django.test import TestCase

from django_hookflow.models import StepExecution
from django_hookflow.models import WorkflowRun
from django_hookflow.models import WorkflowRunStatus
from django_hookflow.persistence import WorkflowPersistence


class TestWorkflowPersistenceCreateRun(TestCase):
    """Tests for WorkflowPersistence.create_run()"""

    def test_create_run_with_data(self):
        """Test creating a workflow run with initial data."""
        run = WorkflowPersistence.create_run(
            run_id="test-run-1",
            workflow_id="test-workflow",
            data={"key": "value"},
        )

        self.assertEqual(run.run_id, "test-run-1")
        self.assertEqual(run.workflow_id, "test-workflow")
        self.assertEqual(run.status, WorkflowRunStatus.PENDING)
        self.assertEqual(run.data, {"key": "value"})
        self.assertIsNone(run.result)
        self.assertEqual(run.error_message, "")
        self.assertIsNotNone(run.created_at)
        self.assertIsNotNone(run.updated_at)
        self.assertIsNone(run.completed_at)

    def test_create_run_without_data(self):
        """Test creating a workflow run without data defaults to empty dict."""
        run = WorkflowPersistence.create_run(
            run_id="test-run-2",
            workflow_id="test-workflow",
        )

        self.assertEqual(run.data, {})

    def test_create_run_persists_to_database(self):
        """Test that create_run persists the record to the database."""
        WorkflowPersistence.create_run(
            run_id="test-run-3",
            workflow_id="test-workflow",
            data={"foo": "bar"},
        )

        # Verify we can retrieve it from the database
        run = WorkflowRun.objects.get(run_id="test-run-3")
        self.assertEqual(run.workflow_id, "test-workflow")
        self.assertEqual(run.data, {"foo": "bar"})


class TestWorkflowPersistenceGetRun(TestCase):
    """Tests for WorkflowPersistence.get_run()"""

    def test_get_run_returns_existing_run(self):
        """Test getting an existing workflow run."""
        WorkflowPersistence.create_run(
            run_id="existing-run",
            workflow_id="test-workflow",
            data={"test": "data"},
        )

        run = WorkflowPersistence.get_run("existing-run")

        self.assertIsNotNone(run)
        self.assertEqual(run.run_id, "existing-run")
        self.assertEqual(run.workflow_id, "test-workflow")

    def test_get_run_returns_none_for_nonexistent_run(self):
        """Test that get_run returns None for non-existent run_id."""
        run = WorkflowPersistence.get_run("nonexistent-run")

        self.assertIsNone(run)


class TestWorkflowPersistenceGetCompletedSteps(TestCase):
    """Tests for WorkflowPersistence.get_completed_steps()"""

    def test_get_completed_steps_returns_empty_dict_for_new_run(self):
        """Test that a new run has no completed steps."""
        WorkflowPersistence.create_run(
            run_id="new-run",
            workflow_id="test-workflow",
        )

        steps = WorkflowPersistence.get_completed_steps("new-run")

        self.assertEqual(steps, {})

    def test_get_completed_steps_returns_saved_steps(self):
        """Test that saved steps are returned correctly."""
        WorkflowPersistence.create_run(
            run_id="run-with-steps",
            workflow_id="test-workflow",
        )

        WorkflowPersistence.save_step("run-with-steps", "step-1", "result-1")
        WorkflowPersistence.save_step(
            "run-with-steps", "step-2", {"key": "value"}
        )

        steps = WorkflowPersistence.get_completed_steps("run-with-steps")

        self.assertEqual(
            steps,
            {
                "step-1": "result-1",
                "step-2": {"key": "value"},
            },
        )

    def test_get_completed_steps_returns_empty_dict_for_nonexistent_run(self):
        """Test that non-existent run returns empty dict."""
        steps = WorkflowPersistence.get_completed_steps("nonexistent-run")

        self.assertEqual(steps, {})


class TestWorkflowPersistenceSaveStep(TestCase):
    """Tests for WorkflowPersistence.save_step()"""

    def test_save_step_creates_step_execution(self):
        """Test that save_step creates a StepExecution record."""
        WorkflowPersistence.create_run(
            run_id="save-step-run",
            workflow_id="test-workflow",
        )

        step = WorkflowPersistence.save_step(
            run_id="save-step-run",
            step_id="step-1",
            result={"data": "value"},
        )

        self.assertIsNotNone(step)
        self.assertEqual(step.step_id, "step-1")
        self.assertEqual(step.result, {"data": "value"})
        self.assertIsNotNone(step.executed_at)

    def test_save_step_updates_workflow_status_to_running(self):
        """Test saving a step updates status from pending to running."""
        WorkflowPersistence.create_run(
            run_id="status-update-run",
            workflow_id="test-workflow",
        )

        WorkflowPersistence.save_step(
            run_id="status-update-run",
            step_id="step-1",
            result="result",
        )

        run = WorkflowPersistence.get_run("status-update-run")
        self.assertEqual(run.status, WorkflowRunStatus.RUNNING)

    def test_save_step_updates_existing_step(self):
        """Test that save_step updates an existing step execution."""
        WorkflowPersistence.create_run(
            run_id="update-step-run",
            workflow_id="test-workflow",
        )

        WorkflowPersistence.save_step(
            run_id="update-step-run",
            step_id="step-1",
            result="original-result",
        )
        WorkflowPersistence.save_step(
            run_id="update-step-run",
            step_id="step-1",
            result="updated-result",
        )

        steps = WorkflowPersistence.get_completed_steps("update-step-run")
        self.assertEqual(steps["step-1"], "updated-result")

        # Should only have one step execution record
        run = WorkflowPersistence.get_run("update-step-run")
        self.assertEqual(run.step_executions.count(), 1)

    def test_save_step_returns_none_for_nonexistent_run(self):
        """Test that save_step returns None for non-existent run."""
        step = WorkflowPersistence.save_step(
            run_id="nonexistent-run",
            step_id="step-1",
            result="result",
        )

        self.assertIsNone(step)

    def test_save_step_handles_complex_result_types(self):
        """Test save_step handles various JSON-serializable types."""
        WorkflowPersistence.create_run(
            run_id="complex-result-run",
            workflow_id="test-workflow",
        )

        # Test with different result types
        WorkflowPersistence.save_step(
            "complex-result-run", "step-string", "string result"
        )
        WorkflowPersistence.save_step("complex-result-run", "step-int", 42)
        WorkflowPersistence.save_step(
            "complex-result-run", "step-list", [1, 2, 3]
        )
        WorkflowPersistence.save_step(
            "complex-result-run", "step-nested", {"nested": {"key": "value"}}
        )
        WorkflowPersistence.save_step("complex-result-run", "step-null", None)

        steps = WorkflowPersistence.get_completed_steps("complex-result-run")

        self.assertEqual(steps["step-string"], "string result")
        self.assertEqual(steps["step-int"], 42)
        self.assertEqual(steps["step-list"], [1, 2, 3])
        self.assertEqual(steps["step-nested"], {"nested": {"key": "value"}})
        self.assertIsNone(steps["step-null"])


class TestWorkflowPersistenceMarkCompleted(TestCase):
    """Tests for WorkflowPersistence.mark_completed()"""

    def test_mark_completed_updates_status(self):
        """Test that mark_completed updates the workflow status."""
        WorkflowPersistence.create_run(
            run_id="complete-run",
            workflow_id="test-workflow",
        )

        run = WorkflowPersistence.mark_completed(
            run_id="complete-run",
            result={"final": "result"},
        )

        self.assertIsNotNone(run)
        self.assertEqual(run.status, WorkflowRunStatus.COMPLETED)
        self.assertEqual(run.result, {"final": "result"})
        self.assertIsNotNone(run.completed_at)

    def test_mark_completed_returns_none_for_nonexistent_run(self):
        """Test that mark_completed returns None for non-existent run."""
        run = WorkflowPersistence.mark_completed(
            run_id="nonexistent-run",
            result="result",
        )

        self.assertIsNone(run)

    def test_mark_completed_persists_to_database(self):
        """Test that mark_completed persists changes to the database."""
        WorkflowPersistence.create_run(
            run_id="persist-complete-run",
            workflow_id="test-workflow",
        )

        WorkflowPersistence.mark_completed(
            run_id="persist-complete-run",
            result="final-result",
        )

        # Verify by fetching fresh from database
        run = WorkflowRun.objects.get(run_id="persist-complete-run")
        self.assertEqual(run.status, WorkflowRunStatus.COMPLETED)
        self.assertEqual(run.result, "final-result")


class TestWorkflowPersistenceMarkFailed(TestCase):
    """Tests for WorkflowPersistence.mark_failed()"""

    def test_mark_failed_updates_status(self):
        """Test that mark_failed updates the workflow status."""
        WorkflowPersistence.create_run(
            run_id="fail-run",
            workflow_id="test-workflow",
        )

        run = WorkflowPersistence.mark_failed(
            run_id="fail-run",
            error_message="Something went wrong",
        )

        self.assertIsNotNone(run)
        self.assertEqual(run.status, WorkflowRunStatus.FAILED)
        self.assertEqual(run.error_message, "Something went wrong")
        self.assertIsNotNone(run.completed_at)

    def test_mark_failed_returns_none_for_nonexistent_run(self):
        """Test that mark_failed returns None for non-existent run."""
        run = WorkflowPersistence.mark_failed(
            run_id="nonexistent-run",
            error_message="error",
        )

        self.assertIsNone(run)

    def test_mark_failed_persists_to_database(self):
        """Test that mark_failed persists changes to the database."""
        WorkflowPersistence.create_run(
            run_id="persist-fail-run",
            workflow_id="test-workflow",
        )

        WorkflowPersistence.mark_failed(
            run_id="persist-fail-run",
            error_message="Database error",
        )

        # Verify by fetching fresh from database
        run = WorkflowRun.objects.get(run_id="persist-fail-run")
        self.assertEqual(run.status, WorkflowRunStatus.FAILED)
        self.assertEqual(run.error_message, "Database error")


class TestWorkflowPersistenceIntegration(TestCase):
    """Integration tests for WorkflowPersistence"""

    def test_full_workflow_lifecycle(self):
        """Test a complete workflow lifecycle from creation to completion."""
        # Create workflow run
        run = WorkflowPersistence.create_run(
            run_id="lifecycle-run",
            workflow_id="integration-workflow",
            data={"input": "data"},
        )
        self.assertEqual(run.status, WorkflowRunStatus.PENDING)

        # Save first step
        WorkflowPersistence.save_step(
            run_id="lifecycle-run",
            step_id="step-1",
            result="step-1-result",
        )

        run = WorkflowPersistence.get_run("lifecycle-run")
        self.assertEqual(run.status, WorkflowRunStatus.RUNNING)

        # Save second step
        WorkflowPersistence.save_step(
            run_id="lifecycle-run",
            step_id="step-2",
            result="step-2-result",
        )

        # Verify completed steps
        steps = WorkflowPersistence.get_completed_steps("lifecycle-run")
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps["step-1"], "step-1-result")
        self.assertEqual(steps["step-2"], "step-2-result")

        # Complete the workflow
        run = WorkflowPersistence.mark_completed(
            run_id="lifecycle-run",
            result={"final": "output"},
        )
        self.assertEqual(run.status, WorkflowRunStatus.COMPLETED)
        self.assertEqual(run.result, {"final": "output"})
        self.assertIsNotNone(run.completed_at)

    def test_workflow_failure_lifecycle(self):
        """Test a workflow lifecycle that ends in failure."""
        # Create workflow run
        WorkflowPersistence.create_run(
            run_id="failure-lifecycle-run",
            workflow_id="failure-workflow",
            data={"input": "data"},
        )

        # Save a step before failure
        WorkflowPersistence.save_step(
            run_id="failure-lifecycle-run",
            step_id="step-1",
            result="step-1-result",
        )

        # Mark as failed
        run = WorkflowPersistence.mark_failed(
            run_id="failure-lifecycle-run",
            error_message="Step 2 failed: Connection timeout",
        )

        self.assertEqual(run.status, WorkflowRunStatus.FAILED)
        self.assertEqual(
            run.error_message, "Step 2 failed: Connection timeout"
        )
        self.assertIsNotNone(run.completed_at)

        # Completed steps should still be available
        steps = WorkflowPersistence.get_completed_steps(
            "failure-lifecycle-run"
        )
        self.assertEqual(steps["step-1"], "step-1-result")


class TestModels(TestCase):
    """Tests for the Django models"""

    def test_workflow_run_str(self):
        """Test WorkflowRun string representation."""
        run = WorkflowPersistence.create_run(
            run_id="str-test-run",
            workflow_id="str-test-workflow",
        )

        expected = "WorkflowRun(str-test-run, str-test-workflow, pending)"
        self.assertEqual(str(run), expected)

    def test_step_execution_str(self):
        """Test StepExecution string representation."""
        WorkflowPersistence.create_run(
            run_id="step-str-run",
            workflow_id="test-workflow",
        )
        step = WorkflowPersistence.save_step(
            run_id="step-str-run",
            step_id="test-step",
            result="result",
        )

        expected = "StepExecution(step-str-run, test-step)"
        self.assertEqual(str(step), expected)

    def test_workflow_run_ordering(self):
        """Test that workflow runs are ordered by created_at descending."""
        WorkflowPersistence.create_run(
            run_id="first-run",
            workflow_id="test-workflow",
        )
        WorkflowPersistence.create_run(
            run_id="second-run",
            workflow_id="test-workflow",
        )

        runs = list(WorkflowRun.objects.all())
        self.assertEqual(runs[0].run_id, "second-run")
        self.assertEqual(runs[1].run_id, "first-run")

    def test_step_execution_unique_together(self):
        """Test that step_id must be unique within a workflow run."""
        from django.db import IntegrityError

        run = WorkflowPersistence.create_run(
            run_id="unique-test-run",
            workflow_id="test-workflow",
        )

        StepExecution.objects.create(
            workflow_run=run,
            step_id="unique-step",
            result="first",
        )

        with self.assertRaises(IntegrityError):
            StepExecution.objects.create(
                workflow_run=run,
                step_id="unique-step",
                result="second",
            )

    def test_step_execution_cascade_delete(self):
        """Test step executions are deleted when workflow is deleted."""
        WorkflowPersistence.create_run(
            run_id="cascade-run",
            workflow_id="test-workflow",
        )
        WorkflowPersistence.save_step("cascade-run", "step-1", "result")
        WorkflowPersistence.save_step("cascade-run", "step-2", "result")

        self.assertEqual(StepExecution.objects.count(), 2)

        WorkflowRun.objects.filter(run_id="cascade-run").delete()

        self.assertEqual(StepExecution.objects.count(), 0)
