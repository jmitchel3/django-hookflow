from __future__ import annotations

from django.db import models
from django.utils import timezone


class WorkflowRunStatus(models.TextChoices):
    """Status choices for workflow runs."""

    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class WorkflowRun(models.Model):
    """
    Tracks workflow executions.

    This model persists the state of workflow runs to survive QStash
    message failures and enable recovery.
    """

    run_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique identifier for this workflow run",
    )
    workflow_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Identifier for the workflow definition",
    )
    status = models.CharField(
        max_length=20,
        choices=WorkflowRunStatus.choices,
        default=WorkflowRunStatus.PENDING,
        help_text="Current status of the workflow run",
    )
    data = models.JSONField(
        default=dict,
        help_text="Initial payload data passed to the workflow",
    )
    result = models.JSONField(
        null=True,
        blank=True,
        help_text="Final result of the workflow if completed",
    )
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="Error message if the workflow failed",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the workflow run was created",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="When the workflow run was last updated",
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the workflow run completed or failed",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Workflow Run"
        verbose_name_plural = "Workflow Runs"

    def __str__(self) -> str:
        return f"WorkflowRun({self.run_id}, {self.workflow_id}, {self.status})"


class StepExecution(models.Model):
    """
    Records step results within a workflow run.

    This model stores the result of each completed step, enabling
    workflow recovery by replaying completed steps from the database.
    """

    workflow_run = models.ForeignKey(
        WorkflowRun,
        on_delete=models.CASCADE,
        related_name="step_executions",
        help_text="The workflow run this step belongs to",
    )
    step_id = models.CharField(
        max_length=255,
        help_text="Identifier for this step within the workflow",
    )
    result = models.JSONField(
        null=True,
        blank=True,
        help_text="Result data from the step execution",
    )
    executed_at = models.DateTimeField(
        default=timezone.now,
        help_text="When this step was executed",
    )

    class Meta:
        unique_together = [("workflow_run", "step_id")]
        ordering = ["executed_at"]
        verbose_name = "Step Execution"
        verbose_name_plural = "Step Executions"

    def __str__(self) -> str:
        return f"StepExecution({self.workflow_run.run_id}, {self.step_id})"
