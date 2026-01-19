from __future__ import annotations

from typing import Any


class HookFlowException(Exception):
    """Custom exception for django-hookflow errors."""

    pass


class WorkflowError(HookFlowException):
    """Exception raised for workflow-related errors."""

    pass


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
