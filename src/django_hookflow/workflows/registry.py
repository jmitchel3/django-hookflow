from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Callable

if TYPE_CHECKING:
    from .decorator import WorkflowWrapper


# Global registry mapping workflow IDs to their wrapper instances
_workflow_registry: dict[str, WorkflowWrapper] = {}


def register_workflow(workflow_id: str, wrapper: WorkflowWrapper) -> None:
    """
    Register a workflow in the global registry.

    Args:
        workflow_id: Unique identifier for the workflow
        wrapper: The WorkflowWrapper instance to register
    """
    if workflow_id in _workflow_registry:
        raise ValueError(f"Workflow '{workflow_id}' is already registered")
    _workflow_registry[workflow_id] = wrapper


def get_workflow(workflow_id: str) -> WorkflowWrapper | None:
    """
    Retrieve a workflow from the registry.

    Args:
        workflow_id: The workflow ID to look up

    Returns:
        The WorkflowWrapper instance if found, None otherwise
    """
    return _workflow_registry.get(workflow_id)


def get_all_workflows() -> dict[str, WorkflowWrapper]:
    """
    Get all registered workflows.

    Returns:
        Dictionary mapping workflow IDs to their wrapper instances
    """
    return _workflow_registry.copy()


def generate_workflow_id(func: Callable) -> str:  # type: ignore[type-arg]
    """
    Generate a unique workflow ID from a function.

    The ID is generated from the module and function name to ensure
    uniqueness across the application.

    Args:
        func: The workflow function

    Returns:
        A unique workflow ID string
    """
    module = func.__module__
    name = func.__qualname__
    return f"{module}.{name}"
