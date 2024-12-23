import requests
from django.conf import settings


def dispatch_workflow(repo, workflow_file, ref="main"):
    """
    Triggers a GitHub Actions workflow dispatch event.

    :param repo: The GitHub repository (e.g., "user/repo").
    :param workflow_file: The workflow file name to trigger.
    :param ref: The Git branch or ref to use. Defaults to "main".
    """
    github_token = getattr(settings, "GITHUB_PERSONAL_ACCESS_TOKEN", None)
    if not github_token:
        raise ValueError("GITHUB_PERSONAL_ACCESS_TOKEN is not set in Django settings.")

    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/dispatches"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {"ref": ref}

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 404:
        raise ValueError(
            f"Resource not found: The repository '{repo}' or workflow file '{workflow_file}' does not exist"
        )
    elif response.status_code != 204:
        raise Exception(
            f"Failed to trigger workflow: {response.status_code}, {response.text}"
        )
