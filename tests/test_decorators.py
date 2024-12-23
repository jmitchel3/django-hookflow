import unittest
from unittest.mock import MagicMock, patch

from django.conf import settings
from hookflow.decorators import trigger_github_workflow
from hookflow.exceptions import HookFlowException
from hookflow.github import trigger_workflow


class TestDecorators(unittest.TestCase):
    def setUp(self):
        # Mock Django settings
        settings.configure(
            GITHUB_PERSONAL_ACCESS_TOKEN="test_github_token",
            GITHUB_DEFAULT_REPO="test_user/test_repo",
        )

    @patch("hookflow.github.requests.post")
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
        mock_post.assert_called_once_with(
            "https://api.github.com/repos/test_user/test_repo/actions/workflows/test_workflow.yml/dispatches",
            json={"ref": "main"},
            headers={
                "Authorization": "token test_github_token",
                "Accept": "application/vnd.github.v3+json",
            },
        )

    @patch("hookflow.github.requests.post")
    def test_decorator_raises_error_on_missing_repo(self, mock_post):
        # Mock a successful response from GitHub API
        mock_post.return_value = MagicMock(status_code=204)

        @trigger_github_workflow(
            workflow_file="test_workflow.yml", repo=None, ref="main"
        )
        def sample_function():
            return "Function executed"

        # Clear default repo in settings
        del settings.GITHUB_DEFAULT_REPO

        with self.assertRaises(HookFlowException) as context:
            sample_function()

        self.assertIn("GitHub repo must be specified", str(context.exception))

    @patch("hookflow.github.requests.post")
    def test_decorator_raises_error_on_missing_workflow(self, mock_post):
        @trigger_github_workflow(
            repo="test_user/test_repo", workflow_file=None, ref="main"
        )
        def sample_function():
            return "Function executed"

        with self.assertRaises(HookFlowException) as context:
            sample_function()

        self.assertIn("A workflow file must be specified", str(context.exception))

    @patch("hookflow.github.requests.post")
    def test_trigger_workflow_handles_github_error(self, mock_post):
        # Mock a failed response from GitHub API
        mock_post.return_value = MagicMock(status_code=400, text="Bad Request")

        with self.assertRaises(Exception) as context:
            trigger_workflow(
                repo="test_user/test_repo",
                workflow_file="invalid_workflow.yml",
                ref="main",
            )

        self.assertIn("Failed to trigger workflow", str(context.exception))
        mock_post.assert_called_once()

    @patch("hookflow.github.requests.post")
    def test_decorator_uses_default_repo_from_settings(self, mock_post):
        # Mock a successful response from GitHub API
        mock_post.return_value = MagicMock(status_code=204)

        @trigger_github_workflow(workflow_file="test_workflow.yml", ref="main")
        def sample_function():
            return "Function executed"

        result = sample_function()

        # Assert the function result
        self.assertEqual(result, "Function executed")

        # Assert the workflow trigger call
        mock_post.assert_called_once_with(
            "https://api.github.com/repos/test_user/test_repo/actions/workflows/test_workflow.yml/dispatches",
            json={"ref": "main"},
            headers={
                "Authorization": "token test_github_token",
                "Accept": "application/vnd.github.v3+json",
            },
        )


if __name__ == "__main__":
    unittest.main()
