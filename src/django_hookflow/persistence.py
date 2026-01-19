from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from .models import StepExecution
from .models import WorkflowRun
from .models import WorkflowRunStatus

logger = logging.getLogger(__name__)


class WorkflowPersistence:
    """
    Persistence utilities for workflow state management.

    This class provides methods to create, read, and update workflow
    run state in the database, enabling recovery from QStash message
    failures.
    """

    @staticmethod
    def create_run(
        run_id: str,
        workflow_id: str,
        data: dict[str, Any] | None = None,
    ) -> WorkflowRun:
        """
        Create a new workflow run record.

        Args:
            run_id: Unique identifier for this workflow run
            workflow_id: Identifier for the workflow definition
            data: Initial payload data for the workflow

        Returns:
            The created WorkflowRun instance
        """
        if data is None:
            data = {}

        workflow_run = WorkflowRun.objects.create(
            run_id=run_id,
            workflow_id=workflow_id,
            status=WorkflowRunStatus.PENDING,
            data=data,
        )
        logger.debug(
            "Created workflow run: run_id=%s, workflow_id=%s",
            run_id,
            workflow_id,
        )
        return workflow_run

    @staticmethod
    def get_run(run_id: str) -> WorkflowRun | None:
        """
        Get a workflow run by its run_id.

        Args:
            run_id: The unique identifier for the workflow run

        Returns:
            The WorkflowRun instance if found, None otherwise
        """
        try:
            return WorkflowRun.objects.get(run_id=run_id)
        except WorkflowRun.DoesNotExist:
            return None

    @staticmethod
    def get_completed_steps(run_id: str) -> dict[str, Any]:
        """
        Load all completed steps for a workflow run as a dictionary.

        Args:
            run_id: The unique identifier for the workflow run

        Returns:
            Dictionary mapping step_id to step result
        """
        try:
            workflow_run = WorkflowRun.objects.get(run_id=run_id)
        except WorkflowRun.DoesNotExist:
            return {}

        step_executions = workflow_run.step_executions.all()
        return {step.step_id: step.result for step in step_executions}

    @staticmethod
    @transaction.atomic
    def save_step(
        run_id: str,
        step_id: str,
        result: Any,
    ) -> StepExecution | None:
        """
        Save a step result for a workflow run.

        Uses select_for_update to ensure thread-safe updates.

        Args:
            run_id: The unique identifier for the workflow run
            step_id: The identifier for the step within the workflow
            result: The result data from the step execution

        Returns:
            The created or updated StepExecution instance, or None if
            the workflow run was not found
        """
        try:
            workflow_run = WorkflowRun.objects.select_for_update().get(
                run_id=run_id
            )
        except WorkflowRun.DoesNotExist:
            logger.warning(
                "Cannot save step: workflow run not found: run_id=%s",
                run_id,
            )
            return None

        # Update workflow status to running if it was pending
        if workflow_run.status == WorkflowRunStatus.PENDING:
            workflow_run.status = WorkflowRunStatus.RUNNING
            workflow_run.save(update_fields=["status", "updated_at"])

        # Create or update the step execution
        step_execution, created = StepExecution.objects.update_or_create(
            workflow_run=workflow_run,
            step_id=step_id,
            defaults={
                "result": result,
                "executed_at": timezone.now(),
            },
        )

        action = "Created" if created else "Updated"
        logger.debug(
            "%s step execution: run_id=%s, step_id=%s",
            action,
            run_id,
            step_id,
        )
        return step_execution

    @staticmethod
    @transaction.atomic
    def mark_completed(run_id: str, result: Any) -> WorkflowRun | None:
        """
        Mark a workflow run as completed.

        Args:
            run_id: The unique identifier for the workflow run
            result: The final result of the workflow

        Returns:
            The updated WorkflowRun instance, or None if not found
        """
        try:
            workflow_run = WorkflowRun.objects.select_for_update().get(
                run_id=run_id
            )
        except WorkflowRun.DoesNotExist:
            logger.warning(
                "Cannot mark completed: workflow run not found: run_id=%s",
                run_id,
            )
            return None

        workflow_run.status = WorkflowRunStatus.COMPLETED
        workflow_run.result = result
        workflow_run.completed_at = timezone.now()
        workflow_run.save(
            update_fields=["status", "result", "completed_at", "updated_at"]
        )

        logger.info(
            "Workflow run completed: run_id=%s",
            run_id,
        )
        return workflow_run

    @staticmethod
    @transaction.atomic
    def mark_failed(run_id: str, error_message: str) -> WorkflowRun | None:
        """
        Mark a workflow run as failed.

        Args:
            run_id: The unique identifier for the workflow run
            error_message: Description of the error that caused the failure

        Returns:
            The updated WorkflowRun instance, or None if not found
        """
        try:
            workflow_run = WorkflowRun.objects.select_for_update().get(
                run_id=run_id
            )
        except WorkflowRun.DoesNotExist:
            logger.warning(
                "Cannot mark failed: workflow run not found: run_id=%s",
                run_id,
            )
            return None

        workflow_run.status = WorkflowRunStatus.FAILED
        workflow_run.error_message = error_message
        workflow_run.completed_at = timezone.now()
        workflow_run.save(
            update_fields=[
                "status",
                "error_message",
                "completed_at",
                "updated_at",
            ]
        )

        logger.info(
            "Workflow run failed: run_id=%s, error=%s",
            run_id,
            error_message,
        )
        return workflow_run

    @staticmethod
    @transaction.atomic
    def increment_retry_attempt(run_id: str) -> int | None:
        """
        Increment the retry attempt counter for a workflow run.

        Args:
            run_id: The unique identifier for the workflow run

        Returns:
            The new retry attempt count, or None if the run was not found
        """
        try:
            workflow_run = WorkflowRun.objects.select_for_update().get(
                run_id=run_id
            )
        except WorkflowRun.DoesNotExist:
            logger.warning(
                "Cannot increment retry: workflow run not found: run_id=%s",
                run_id,
            )
            return None

        workflow_run.retry_attempt += 1
        workflow_run.save(update_fields=["retry_attempt", "updated_at"])

        logger.debug(
            "Incremented retry attempt: run_id=%s, attempt=%d",
            run_id,
            workflow_run.retry_attempt,
        )
        return workflow_run.retry_attempt

    @staticmethod
    @transaction.atomic
    def reset_retry_attempt(run_id: str) -> bool:
        """
        Reset the retry attempt counter to zero for a workflow run.

        Typically called after a successful step completion.

        Args:
            run_id: The unique identifier for the workflow run

        Returns:
            True if successful, False if the run was not found
        """
        try:
            workflow_run = WorkflowRun.objects.select_for_update().get(
                run_id=run_id
            )
        except WorkflowRun.DoesNotExist:
            logger.warning(
                "Cannot reset retry: workflow run not found: run_id=%s",
                run_id,
            )
            return False

        workflow_run.retry_attempt = 0
        workflow_run.save(update_fields=["retry_attempt", "updated_at"])

        logger.debug(
            "Reset retry attempt: run_id=%s",
            run_id,
        )
        return True
