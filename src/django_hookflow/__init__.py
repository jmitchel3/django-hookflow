from __future__ import annotations

__version__ = "0.0.1"

from .decorators import trigger_github_workflow
from .github import dispatch_workflow
from .workflows import WorkflowContext
from .workflows import workflow

__all__ = [
    "WorkflowContext",
    "dispatch_workflow",
    "trigger_github_workflow",
    "workflow",
]
