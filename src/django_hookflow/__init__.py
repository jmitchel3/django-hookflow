__version__ = "0.0.1"

from .decorators import trigger_github_workflow
from .github import dispatch_workflow

__all__ = ["trigger_github_workflow", "dispatch_workflow"]
