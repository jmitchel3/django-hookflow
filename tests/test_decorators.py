from __future__ import annotations

import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from django.conf import settings

from django_hookflow.decorators import trigger_github_workflow
from django_hookflow.exceptions import HookFlowException
from django_hookflow.github import dispatch_workflow


class TestDecorators(unittest.TestCase):
    @patch("django_hookflow.github.requests.post")
    def test_decorator_triggers_workflow(self, mock_post):
        # Mock a successful response from GitHub API
        mock_post.return_value = MagicMock(status_code=204)

        @trigger_github_workflow(workflow_file="test_workflow.yml", ref="main")
        def sample_function():
            return "Function executed"

        result = sample_function()

        # Assert the function result
        self.assertEqual(result, "Function executed")

        # Assert the workflow trigger call
        expected_url = (
            "https://api.github.com/repos/test/repo"
            "/actions/workflows/test_workflow.yml/dispatches"
        )
        mock_post.assert_called_once_with(
            expected_url,
            json={"ref": "main"},
            headers={
                "Authorization": "token test-token",
                "Accept": "application/vnd.github.v3+json",
            },
        )

    @patch("django_hookflow.github.requests.post")
    def test_decorator_raises_error_on_missing_repo(self, mock_post):
        # Mock a successful response from GitHub API
        mock_post.return_value = MagicMock(status_code=204)

        @trigger_github_workflow(
            workflow_file="test_workflow.yml", repo=None, ref="main"
        )
        def sample_function():
            return "Function executed"

        # Clear default repo in settings temporarily
        original_repo = settings.GITHUB_DEFAULT_REPO
        del settings.GITHUB_DEFAULT_REPO

        try:
            with self.assertRaises(HookFlowException) as context:
                sample_function()

            err_msg = str(context.exception)
            self.assertIn("GitHub repo must be specified", err_msg)
        finally:
            settings.GITHUB_DEFAULT_REPO = original_repo

    @patch("django_hookflow.github.requests.post")
    def test_decorator_raises_error_on_missing_workflow(self, mock_post):
        @trigger_github_workflow(
            repo="test_user/test_repo", workflow_file=None, ref="main"
        )
        def sample_function():
            return "Function executed"

        with self.assertRaises(HookFlowException) as context:
            sample_function()

        err_msg = str(context.exception)
        self.assertIn("A workflow file must be specified", err_msg)

    @patch("django_hookflow.github.requests.post")
    def test_dispatch_workflow_handles_github_error(self, mock_post):
        # Mock a failed response from GitHub API
        mock_post.return_value = MagicMock(status_code=400, text="Bad Request")

        with self.assertRaises(Exception) as context:
            dispatch_workflow(
                repo="test_user/test_repo",
                workflow_file="invalid_workflow.yml",
                ref="main",
            )

        self.assertIn("Failed to trigger workflow", str(context.exception))
        mock_post.assert_called_once()

    @patch("django_hookflow.github.requests.post")
    def test_decorator_uses_default_repo_from_settings(self, mock_post):
        # Mock a successful response from GitHub API
        mock_post.return_value = MagicMock(status_code=204)

        @trigger_github_workflow(workflow_file="test_workflow.yml", ref="main")
        def sample_function():
            return "Function executed"

        result = sample_function()

        # Assert the function result
        self.assertEqual(result, "Function executed")

        # Assert the workflow trigger call uses default repo from settings
        expected_url = (
            "https://api.github.com/repos/test/repo"
            "/actions/workflows/test_workflow.yml/dispatches"
        )
        mock_post.assert_called_once_with(
            expected_url,
            json={"ref": "main"},
            headers={
                "Authorization": "token test-token",
                "Accept": "application/vnd.github.v3+json",
            },
        )


if __name__ == "__main__":
    unittest.main()
