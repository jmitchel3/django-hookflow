from __future__ import annotations

from typing import Any


class HookFlowException(Exception):
    """Custom exception for django-hookflow errors."""

    pass


class WorkflowError(HookFlowException):
    """Exception raised for workflow-related errors."""

    pass


class ExecutionTimeoutError(WorkflowError):
    """
    Raised when workflow execution exceeds the configured timeout.

    This is a cooperative timeout using threading. It checks at periodic
    intervals and will not interrupt blocking I/O operations immediately.

    Attributes:
        timeout_seconds: The timeout duration that was exceeded
        workflow_id: The workflow that timed out (if available)
        run_id: The run that timed out (if available)
    """

    def __init__(
        self,
        message: str,
        timeout_seconds: int | None = None,
        workflow_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.timeout_seconds = timeout_seconds
        self.workflow_id = workflow_id
        self.run_id = run_id


class StepCompleted(Exception):
    """
    Raised to halt workflow execution and schedule the next step.

    This exception is used internally by the workflow system to signal
    that a step has completed and the workflow should yield control
    back to QStash for the next invocation.
    """

    def __init__(
        self,
        step_id: str,
        result: Any,
        completed_steps: dict[str, Any],
    ) -> None:
        self.step_id = step_id
        self.result = result
        self.completed_steps = completed_steps
        super().__init__(f"Step '{step_id}' completed")
