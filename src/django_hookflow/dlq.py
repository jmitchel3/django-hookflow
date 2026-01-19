from __future__ import annotations

import re
import uuid
from typing import Any

from django.db import models
from django.utils import timezone

_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)token\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)password\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)secret\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)authorization\s*[:=]\s*[^\s,;]+"),
]


def _sanitize_traceback(traceback_text: str) -> str:
    sanitized = traceback_text
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub("<redacted>", sanitized)
    return sanitized


class DeadLetterEntry(models.Model):
    """
    Model for storing failed workflow executions in a dead-letter queue.

    When a workflow step fails and exhausts all retries, the failure details
    are recorded here for later analysis and potential replay.
    """

    workflow_id = models.CharField(max_length=255, db_index=True)
    run_id = models.CharField(max_length=255, db_index=True)
    step_id = models.CharField(max_length=255, blank=True, default="")
    payload = models.JSONField()
    completed_steps = models.JSONField(
        default=dict,
        help_text="Completed steps at failure for replay",
    )
    error_message = models.TextField()
    error_traceback = models.TextField(blank=True, default="")
    attempt_count = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    replayed_at = models.DateTimeField(null=True, blank=True)
    is_replayed = models.BooleanField(default=False)

    class Meta:
        app_label = "django_hookflow"
        verbose_name = "Dead Letter Entry"
        verbose_name_plural = "Dead Letter Entries"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["workflow_id", "run_id"],
                name="dlq_workflow_run_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"DLQ: {self.workflow_id} / {self.run_id}"

    @classmethod
    def add_entry(
        cls,
        workflow_id: str,
        run_id: str,
        payload: dict[str, Any],
        error_message: str,
        step_id: str = "",
        error_traceback: str = "",
        attempt_count: int = 1,
        completed_steps: dict[str, Any] | None = None,
    ) -> DeadLetterEntry:
        """
        Create a new dead-letter queue entry for a failed workflow execution.

        Args:
            workflow_id: The workflow's unique identifier
            run_id: The unique run identifier
            payload: The full workflow payload at time of failure
            error_message: The error message from the exception
            step_id: Optional step ID where the failure occurred
            error_traceback: Optional full traceback string
            attempt_count: Number of attempts made before failure
            completed_steps: Completed steps at time of failure for replay

        Returns:
            The created DeadLetterEntry instance
        """
        if completed_steps is None:
            completed_steps = {}

        sanitized_traceback = _sanitize_traceback(error_traceback)

        return cls.objects.create(
            workflow_id=workflow_id,
            run_id=run_id,
            step_id=step_id,
            payload=payload,
            completed_steps=completed_steps,
            error_message=error_message,
            error_traceback=sanitized_traceback,
            attempt_count=attempt_count,
        )

    def replay(self) -> str:
        """
        Replay this failed workflow by triggering a new run.

        This creates a new workflow execution with the same payload but a new
        run ID. The entry is marked as replayed.

        Returns:
            The new run_id for the replayed workflow

        Raises:
            WorkflowError: If the workflow is not found in the registry
        """
        from django_hookflow.workflows.registry import get_workflow

        workflow = get_workflow(self.workflow_id)
        if workflow is None:
            from django_hookflow.exceptions import WorkflowError

            raise WorkflowError(
                f"Cannot replay: workflow '{self.workflow_id}' not found"
            )

        # Generate a new run ID for the replay
        new_run_id = f"replay-{uuid.uuid4()}"

        # Trigger the workflow with original data but new run ID
        data = self.payload.get("data", {})
        workflow.trigger(data=data, run_id=new_run_id)

        # Mark this entry as replayed
        self.is_replayed = True
        self.replayed_at = timezone.now()
        self.save(update_fields=["is_replayed", "replayed_at"])

        return new_run_id
