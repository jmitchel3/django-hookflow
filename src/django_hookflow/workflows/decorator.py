from __future__ import annotations

import functools
import uuid
from typing import Any
from typing import Callable
from typing import TypeVar

from django.conf import settings
from qstash import QStash

from django_hookflow.exceptions import WorkflowError

from .context import StepManager
from .context import WorkflowContext
from .registry import generate_workflow_id
from .registry import register_workflow


def _is_persistence_enabled() -> bool:
    """Check if workflow persistence is enabled."""
    return getattr(settings, "DJANGO_HOOKFLOW_PERSISTENCE_ENABLED", False)


def _get_persistence():
    """Lazy import of WorkflowPersistence to avoid circular imports."""
    from django_hookflow.persistence import WorkflowPersistence

    return WorkflowPersistence


T = TypeVar("T")
WorkflowFunc = Callable[[WorkflowContext], T]


class WorkflowWrapper:
    """
    Wrapper class for workflow functions.

    This class wraps a workflow function and provides:
    - A `.trigger()` method to start the workflow
    - Registration in the global workflow registry
    - Access to the underlying function for execution
    """

    def __init__(
        self,
        func: WorkflowFunc[T],
        workflow_id: str | None = None,
    ) -> None:
        """
        Initialize the WorkflowWrapper.

        Args:
            func: The workflow function to wrap
            workflow_id: Optional custom workflow ID (auto-generated if None)
        """
        self._func = func
        self._workflow_id = workflow_id or generate_workflow_id(func)
        functools.update_wrapper(self, func)

    @property
    def workflow_id(self) -> str:
        """The unique identifier for this workflow."""
        return self._workflow_id

    def __call__(self, ctx: WorkflowContext) -> T:
        """
        Execute the workflow function.

        This is called by the webhook handler, not directly by users.

        Args:
            ctx: The WorkflowContext for this execution

        Returns:
            The result of the workflow function
        """
        return self._func(ctx)

    def trigger(
        self,
        data: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> str:
        """
        Trigger a new workflow execution.

        This publishes a message to QStash to start the workflow.
        The workflow will execute asynchronously via webhooks.

        Args:
            data: Initial payload to pass to the workflow
            run_id: Optional custom run ID (auto-generated if not provided)

        Returns:
            The run_id for this workflow execution

        Raises:
            WorkflowError: If the workflow cannot be triggered
        """
        if data is None:
            data = {}

        if run_id is None:
            run_id = str(uuid.uuid4())

        # Create workflow run record if persistence is enabled
        if _is_persistence_enabled():
            _get_persistence().create_run(
                run_id=run_id,
                workflow_id=self._workflow_id,
                data=data,
            )

        # Get configuration from settings
        qstash_token = getattr(settings, "QSTASH_TOKEN", None)
        if not qstash_token:
            raise WorkflowError("QSTASH_TOKEN is not set in Django settings")

        domain = getattr(settings, "DJANGO_HOOKFLOW_DOMAIN", None)
        if not domain:
            msg = "DJANGO_HOOKFLOW_DOMAIN is not set in Django settings"
            raise WorkflowError(msg)

        webhook_path = getattr(
            settings, "DJANGO_HOOKFLOW_WEBHOOK_PATH", "/hookflow/"
        )

        # Build the webhook URL
        base_url = domain.rstrip("/")
        webhook_url = f"{base_url}{webhook_path}workflow/{self._workflow_id}/"

        # Prepare the payload
        payload = {
            "workflow_id": self._workflow_id,
            "run_id": run_id,
            "data": data,
            "completed_steps": {},
        }

        # Publish to QStash
        try:
            client = QStash(token=qstash_token)
            client.message.publish_json(
                url=webhook_url,
                body=payload,
            )
        except Exception as e:
            raise WorkflowError(f"Failed to trigger workflow: {e}") from e

        return run_id

    def execute(
        self,
        data: dict[str, Any],
        run_id: str,
        completed_steps: dict[str, Any],
    ) -> Any:
        """
        Execute the workflow with given state.

        This is called by the webhook handler to execute the workflow
        with the current state (completed steps from previous invocations).

        Args:
            data: The initial workflow payload
            run_id: The unique run identifier
            completed_steps: Results from previously completed steps

        Returns:
            The final result if workflow completes, or partial state
        """
        step_manager = StepManager(
            completed_steps=completed_steps,
            run_id=run_id,
            workflow_id=self._workflow_id,
        )

        ctx = WorkflowContext(
            data=data,
            step=step_manager,
            run_id=run_id,
            workflow_id=self._workflow_id,
        )

        return self._func(ctx)


def workflow(
    func: WorkflowFunc[T] | None = None,
    *,
    workflow_id: str | None = None,
) -> WorkflowWrapper | Callable[[WorkflowFunc[T]], WorkflowWrapper]:
    """
    Decorator to define a durable workflow function.

    The decorated function receives a WorkflowContext and can use
    ctx.step.run() to execute durable steps that survive restarts.

    Can be used with or without parentheses:

        @workflow
        def my_workflow(ctx):
            ...

        @workflow(workflow_id="custom-id")
        def my_workflow(ctx):
            ...

    Args:
        func: The workflow function (when used without parentheses)
        workflow_id: Optional custom workflow ID

    Returns:
        WorkflowWrapper instance with .trigger() method
    """

    def decorator(fn: WorkflowFunc[T]) -> WorkflowWrapper:
        wrapper = WorkflowWrapper(fn, workflow_id=workflow_id)
        register_workflow(wrapper.workflow_id, wrapper)
        return wrapper

    if func is not None:
        # Called without parentheses: @workflow
        return decorator(func)

    # Called with parentheses: @workflow() or @workflow(workflow_id="...")
    return decorator
