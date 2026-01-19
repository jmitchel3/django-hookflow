from __future__ import annotations

import time
from typing import Any
from typing import Callable
from typing import TypeVar

from django_hookflow.exceptions import StepCompleted
from django_hookflow.exceptions import WorkflowError

T = TypeVar("T")


class StepManager:
    """
    Manages step execution with durability guarantees.

    The StepManager tracks completed steps and their results. When a step
    that has already completed is encountered, it returns the cached result
    instead of re-executing the step function.
    """

    def __init__(
        self,
        completed_steps: dict[str, Any],
        run_id: str,
        workflow_id: str,
    ) -> None:
        """
        Initialize the StepManager.

        Args:
            completed_steps: Dictionary mapping step IDs to their results
            run_id: Unique identifier for this workflow run
            workflow_id: The workflow's unique identifier
        """
        self._completed_steps = completed_steps
        self._run_id = run_id
        self._workflow_id = workflow_id

    def run(
        self,
        step_id: str,
        fn: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """
        Execute a step with durability.

        Returns cached result if already complete.

        If the step has already been executed in a previous invocation, the
        cached result is returned immediately. Otherwise, the step function
        is executed and a StepCompleted exception is raised to signal that
        execution should yield back to QStash.

        Args:
            step_id: Unique identifier for this step within the workflow
            fn: The function to execute
            *args: Positional arguments to pass to the function
            **kwargs: Keyword arguments to pass to the function

        Returns:
            The result of the step function (either cached or freshly computed)

        Raises:
            StepCompleted: After executing a new step to signal yield to QStash
            WorkflowError: If the step function raises an exception
        """
        # Check if step already completed
        if step_id in self._completed_steps:
            return self._completed_steps[step_id]  # type: ignore[return-value]

        # Execute the step
        try:
            result = fn(*args, **kwargs)
        except Exception as e:
            raise WorkflowError(f"Step '{step_id}' failed: {e}") from e

        # Store result and signal completion
        new_completed = self._completed_steps.copy()
        new_completed[step_id] = result

        raise StepCompleted(
            step_id=step_id,
            result=result,
            completed_steps=new_completed,
        )

    def sleep(self, step_id: str, seconds: int) -> None:
        """
        Sleep without consuming runtime using QStash delay.

        This creates a durable sleep that doesn't consume server resources.
        The workflow will be re-invoked after the specified delay.

        Args:
            step_id: Unique identifier for this sleep step
            seconds: Number of seconds to sleep
        """
        # Check if sleep already completed
        if step_id in self._completed_steps:
            return

        # Record the sleep as completed and signal
        new_completed = self._completed_steps.copy()
        new_completed[step_id] = {
            "slept_for": seconds,
            "timestamp": time.time(),
        }

        raise StepCompleted(
            step_id=step_id,
            result=new_completed[step_id],
            completed_steps=new_completed,
        )

    def call(
        self,
        step_id: str,
        url: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        verify: bool | None = None,
    ) -> Any:
        """
        Make an external HTTP call as a durable step.

        This executes an HTTP request and stores the result durably.
        On retry, the cached result is returned without re-executing.

        Args:
            step_id: Unique identifier for this call step
            url: The URL to call
            method: HTTP method (GET, POST, etc.)
            body: Optional request body for POST/PUT requests
            headers: Optional additional headers
            verify: Override SSL verification for this call

        Returns:
            The HTTP response data
        """
        import requests
        from django.conf import settings

        # Check if call already completed
        if step_id in self._completed_steps:
            return self._completed_steps[step_id]

        # Execute the HTTP call
        try:
            verify_setting = getattr(
                settings,
                "DJANGO_HOOKFLOW_VERIFY_SSL",
                True,
            )
            if verify is None:
                verify_value = verify_setting
            elif verify_setting:
                verify_value = verify
            else:
                verify_value = True

            response = requests.request(
                method=method,
                url=url,
                json=body,
                headers=headers,
                timeout=30,
                verify=verify_value,
            )
            response.raise_for_status()
            result = {
                "status_code": response.status_code,
                "data": response.json() if response.content else None,
            }
        except requests.exceptions.RequestException as e:
            msg = f"HTTP call in step '{step_id}' failed: {e}"
            raise WorkflowError(msg) from e

        # Store result and signal completion
        new_completed = self._completed_steps.copy()
        new_completed[step_id] = result

        raise StepCompleted(
            step_id=step_id,
            result=result,
            completed_steps=new_completed,
        )


class WorkflowContext:
    """
    Context object passed to workflow functions.

    The WorkflowContext provides access to:
    - The initial workflow data/payload
    - The step manager for executing durable steps
    - The unique run ID for this workflow execution
    """

    def __init__(
        self,
        data: dict[str, Any],
        step: StepManager,
        run_id: str,
        workflow_id: str,
    ) -> None:
        """
        Initialize the WorkflowContext.

        Args:
            data: The initial payload passed when triggering the workflow
            step: The StepManager instance for this run
            run_id: Unique identifier for this workflow run
            workflow_id: The workflow's unique identifier
        """
        self._data = data
        self._step = step
        self._run_id = run_id
        self._workflow_id = workflow_id

    @property
    def data(self) -> dict[str, Any]:
        """The initial payload passed when triggering the workflow."""
        return self._data

    @property
    def step(self) -> StepManager:
        """The step manager for executing durable steps."""
        return self._step

    @property
    def run_id(self) -> str:
        """Unique identifier for this workflow run."""
        return self._run_id

    @property
    def workflow_id(self) -> str:
        """The workflow's unique identifier."""
        return self._workflow_id
