import functools

from django.conf import settings

from .exceptions import HookFlowException
from .github import dispatch_workflow


def trigger_github_workflow(repo=None, workflow_file=None, ref="main"):
    """
    Decorator to trigger a GitHub Actions workflow after function execution.

    :param repo: The GitHub repository (e.g., "user/repo"). Defaults to settings.GITHUB_DEFAULT_REPO.
    :param workflow_file: The workflow file name to trigger.
    :param ref: The Git branch or ref to use. Defaults to "main".
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Execute the original function
            result = func(*args, **kwargs)

            # Use settings default if repo is not provided
            github_repo = repo or getattr(settings, "GITHUB_DEFAULT_REPO", None)
            if not github_repo:
                raise HookFlowException(
                    "GitHub repo must be specified either in the decorator or settings."
                )

            # Ensure workflow_file is provided
            if not workflow_file:
                raise HookFlowException(
                    "A workflow file must be specified in the decorator."
                )

            # Trigger the GitHub Actions workflow
            dispatch_workflow(github_repo, workflow_file, ref)
            return result

        return wrapper

    return decorator
