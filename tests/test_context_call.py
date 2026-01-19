from __future__ import annotations

import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

import requests

from django_hookflow.exceptions import StepCompleted
from django_hookflow.exceptions import WorkflowError
from django_hookflow.workflows.context import StepManager


class TestStepManagerCall(unittest.TestCase):
    def setUp(self):
        self.manager = StepManager(
            completed_steps={},
            run_id="test-run",
            workflow_id="test-workflow",
        )

    def test_call_returns_cached_result_if_step_completed(self):
        """Test that call() returns cached result if step already done."""
        cached_result = {"status_code": 200, "data": {"cached": True}}
        manager = StepManager(
            completed_steps={"api-call-1": cached_result},
            run_id="test-run",
            workflow_id="test-workflow",
        )

        result = manager.call("api-call-1", "https://api.example.com/data")
        self.assertEqual(result, cached_result)

    @patch("requests.request")
    def test_call_makes_get_request_with_correct_params(self, mock_request):
        """Test that call() makes GET request with correct params."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"success": true}'
        mock_response.json.return_value = {"success": True}
        mock_request.return_value = mock_response

        with self.assertRaises(StepCompleted) as context:
            self.manager.call("get-step", "https://api.example.com/data")

        mock_request.assert_called_once_with(
            method="GET",
            url="https://api.example.com/data",
            json=None,
            headers=None,
            timeout=30,
            verify=True,
        )
        self.assertEqual(context.exception.step_id, "get-step")
        self.assertEqual(context.exception.result["status_code"], 200)
        self.assertEqual(context.exception.result["data"], {"success": True})

    @patch("requests.request")
    def test_call_makes_post_request_with_body(self, mock_request):
        """Test that call() makes POST request with body."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.content = b'{"id": 123}'
        mock_response.json.return_value = {"id": 123}
        mock_request.return_value = mock_response

        body = {"name": "test", "value": 42}

        with self.assertRaises(StepCompleted) as context:
            self.manager.call(
                "post-step",
                "https://api.example.com/create",
                method="POST",
                body=body,
            )

        mock_request.assert_called_once_with(
            method="POST",
            url="https://api.example.com/create",
            json=body,
            headers=None,
            timeout=30,
            verify=True,
        )
        self.assertEqual(context.exception.result["status_code"], 201)
        self.assertEqual(context.exception.result["data"], {"id": 123})

    @patch("requests.request")
    def test_call_passes_custom_headers(self, mock_request):
        """Test that call() passes custom headers."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"authenticated": true}'
        mock_response.json.return_value = {"authenticated": True}
        mock_request.return_value = mock_response

        custom_headers = {
            "Authorization": "Bearer token123",
            "X-Custom-Header": "custom-value",
        }

        with self.assertRaises(StepCompleted):
            self.manager.call(
                "header-step",
                "https://api.example.com/auth",
                headers=custom_headers,
            )

        mock_request.assert_called_once_with(
            method="GET",
            url="https://api.example.com/auth",
            json=None,
            headers=custom_headers,
            timeout=30,
            verify=True,
        )

    @patch("requests.request")
    def test_call_allows_verify_override_when_enabled(self, mock_request):
        """Test that verify override applies when setting is enabled."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"ok": true}'
        mock_response.json.return_value = {"ok": True}
        mock_request.return_value = mock_response

        with patch(
            "django.conf.settings.DJANGO_HOOKFLOW_VERIFY_SSL",
            True,
            create=True,
        ):
            with self.assertRaises(StepCompleted):
                self.manager.call(
                    "verify-step",
                    "https://api.example.com/verify",
                    verify=False,
                )

        mock_request.assert_called_once_with(
            method="GET",
            url="https://api.example.com/verify",
            json=None,
            headers=None,
            timeout=30,
            verify=False,
        )

    @patch("requests.request")
    def test_call_forces_verify_when_disabled_globally(self, mock_request):
        """Test that verify remains True when setting is disabled."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"ok": true}'
        mock_response.json.return_value = {"ok": True}
        mock_request.return_value = mock_response

        with patch(
            "django.conf.settings.DJANGO_HOOKFLOW_VERIFY_SSL",
            False,
            create=True,
        ):
            with self.assertRaises(StepCompleted):
                self.manager.call(
                    "verify-step",
                    "https://api.example.com/verify",
                    verify=False,
                )

        mock_request.assert_called_once_with(
            method="GET",
            url="https://api.example.com/verify",
            json=None,
            headers=None,
            timeout=30,
            verify=True,
        )

    @patch("requests.request")
    def test_call_handles_empty_response_204(self, mock_request):
        """Test that call() handles empty response (204 No Content)."""
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.content = b""
        mock_request.return_value = mock_response

        with self.assertRaises(StepCompleted) as context:
            self.manager.call(
                "delete-step",
                "https://api.example.com/resource/1",
                method="DELETE",
            )

        self.assertEqual(context.exception.result["status_code"], 204)
        self.assertIsNone(context.exception.result["data"])

    @patch("requests.request")
    def test_call_raises_workflow_error_on_connection_error(
        self, mock_request
    ):
        """Test that call() raises WorkflowError on ConnectionError."""
        mock_request.side_effect = requests.exceptions.ConnectionError(
            "Connection refused"
        )

        with self.assertRaises(WorkflowError) as context:
            self.manager.call("conn-step", "https://api.example.com/data")

        self.assertIn("conn-step", str(context.exception))
        self.assertIn("failed", str(context.exception))

    @patch("requests.request")
    def test_call_raises_workflow_error_on_timeout(self, mock_request):
        """Test that call() raises WorkflowError on Timeout."""
        mock_request.side_effect = requests.exceptions.Timeout(
            "Request timed out"
        )

        with self.assertRaises(WorkflowError) as context:
            self.manager.call("timeout-step", "https://api.example.com/slow")

        self.assertIn("timeout-step", str(context.exception))
        self.assertIn("failed", str(context.exception))

    @patch("requests.request")
    def test_call_raises_workflow_error_on_http_error(self, mock_request):
        """Test that call() raises WorkflowError on HTTPError."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = (
            requests.exceptions.HTTPError("500 Server Error")
        )
        mock_request.return_value = mock_response

        with self.assertRaises(WorkflowError) as context:
            self.manager.call(
                "http-error-step", "https://api.example.com/error"
            )

        self.assertIn("http-error-step", str(context.exception))
        self.assertIn("failed", str(context.exception))

    @patch("requests.request")
    def test_call_stores_result_in_completed_steps(self, mock_request):
        """Test that call() stores result in completed_steps dict."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"stored": true}'
        mock_response.json.return_value = {"stored": True}
        mock_request.return_value = mock_response

        with self.assertRaises(StepCompleted) as context:
            self.manager.call("store-step", "https://api.example.com/data")

        expected_result = {"status_code": 200, "data": {"stored": True}}
        self.assertEqual(
            context.exception.completed_steps["store-step"], expected_result
        )

    @patch("requests.request")
    def test_call_put_method_works(self, mock_request):
        """Test that PUT method works."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"updated": true}'
        mock_response.json.return_value = {"updated": True}
        mock_request.return_value = mock_response

        body = {"name": "updated_name"}

        with self.assertRaises(StepCompleted) as context:
            self.manager.call(
                "put-step",
                "https://api.example.com/resource/1",
                method="PUT",
                body=body,
            )

        mock_request.assert_called_once_with(
            method="PUT",
            url="https://api.example.com/resource/1",
            json=body,
            headers=None,
            timeout=30,
            verify=True,
        )
        self.assertEqual(context.exception.result["status_code"], 200)

    @patch("requests.request")
    def test_call_patch_method_works(self, mock_request):
        """Test that PATCH method works."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"patched": true}'
        mock_response.json.return_value = {"patched": True}
        mock_request.return_value = mock_response

        body = {"field": "patched_value"}

        with self.assertRaises(StepCompleted) as context:
            self.manager.call(
                "patch-step",
                "https://api.example.com/resource/1",
                method="PATCH",
                body=body,
            )

        mock_request.assert_called_once_with(
            method="PATCH",
            url="https://api.example.com/resource/1",
            json=body,
            headers=None,
            timeout=30,
            verify=True,
        )
        self.assertEqual(context.exception.result["status_code"], 200)

    @patch("requests.request")
    def test_call_delete_method_works(self, mock_request):
        """Test that DELETE method works."""
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.content = b""
        mock_request.return_value = mock_response

        with self.assertRaises(StepCompleted) as context:
            self.manager.call(
                "delete-step",
                "https://api.example.com/resource/1",
                method="DELETE",
            )

        mock_request.assert_called_once_with(
            method="DELETE",
            url="https://api.example.com/resource/1",
            json=None,
            headers=None,
            timeout=30,
            verify=True,
        )
        self.assertEqual(context.exception.result["status_code"], 204)


if __name__ == "__main__":
    unittest.main()
