from __future__ import annotations

import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from django.test import RequestFactory
from django.test import override_settings

from django_hookflow.exceptions import WorkflowError
from django_hookflow.workflows.handlers import publish_next_step
from django_hookflow.workflows.handlers import verify_qstash_signature


class TestVerifyQstashSignature(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("django_hookflow.qstash.receiver.QStashReceiver")
    def test_successful_verification_with_valid_signature(
        self, mock_receiver_class
    ):
        """Test successful signature verification with valid signature."""
        mock_receiver = MagicMock()
        mock_receiver.verify.return_value = {"iss": "Upstash"}
        mock_receiver_class.return_value = mock_receiver

        request = self.factory.post(
            "/hookflow/workflow/test/",
            data='{"test": "data"}',
            content_type="application/json",
            HTTP_UPSTASH_SIGNATURE="valid-signature",
        )

        result = verify_qstash_signature(request)

        self.assertTrue(result)
        mock_receiver_class.assert_called_once()
        mock_receiver.verify.assert_called_once()

    @patch("django_hookflow.qstash.receiver.QStashReceiver")
    def test_failed_verification_raises_workflow_error(
        self, mock_receiver_class
    ):
        """Test that failed verification raises WorkflowError."""
        mock_receiver = MagicMock()
        mock_receiver.verify.side_effect = WorkflowError("Invalid signature")
        mock_receiver_class.return_value = mock_receiver

        request = self.factory.post(
            "/hookflow/workflow/test/",
            data='{"test": "data"}',
            content_type="application/json",
            HTTP_UPSTASH_SIGNATURE="invalid-signature",
        )

        with self.assertRaises(WorkflowError) as context:
            verify_qstash_signature(request)

        self.assertIn("Invalid signature", str(context.exception))


class TestPublishNextStep(unittest.TestCase):
    def test_raises_error_when_domain_not_set(self):
        """Test error when neither domain setting is set."""
        with override_settings(DJANGO_HOOKFLOW_DOMAIN=None):
            with self.assertRaises(WorkflowError) as context:
                publish_next_step(
                    workflow_id="test-workflow",
                    run_id="test-run",
                    data={"key": "value"},
                    completed_steps={},
                )

            self.assertIn("DJANGO_HOOKFLOW_DOMAIN", str(context.exception))

    @patch("django_hookflow.workflows.handlers.get_qstash_client")
    def test_publishes_message_without_delay(self, mock_get_client):
        """Test that message is published without delay."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        with override_settings(
            DJANGO_HOOKFLOW_DOMAIN="https://example.com",
            DJANGO_HOOKFLOW_WEBHOOK_PATH="/hookflow/",
        ):
            publish_next_step(
                workflow_id="test-workflow",
                run_id="test-run",
                data={"key": "value"},
                completed_steps={},
            )

        call_kwargs = mock_client.publish_json.call_args.kwargs
        self.assertEqual(
            call_kwargs["url"],
            "https://example.com/hookflow/workflow/test-workflow/",
        )
        self.assertEqual(call_kwargs["body"]["workflow_id"], "test-workflow")
        self.assertEqual(call_kwargs["body"]["run_id"], "test-run")
        self.assertEqual(call_kwargs["body"]["data"], {"key": "value"})
        self.assertEqual(call_kwargs["body"]["completed_steps"], {})
        # No delay should be passed
        self.assertNotIn("delay", call_kwargs)

    @patch("django_hookflow.workflows.handlers.get_qstash_client")
    def test_publishes_message_with_explicit_delay_seconds(
        self, mock_get_client
    ):
        """Test that message is published with explicit delay_seconds."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        with override_settings(
            DJANGO_HOOKFLOW_DOMAIN="https://example.com",
            DJANGO_HOOKFLOW_WEBHOOK_PATH="/hookflow/",
        ):
            publish_next_step(
                workflow_id="test-workflow",
                run_id="test-run",
                data={"key": "value"},
                completed_steps={},
                delay_seconds=30,
            )

        call_kwargs = mock_client.publish_json.call_args.kwargs
        self.assertEqual(call_kwargs["delay"], "30s")

    @patch("django_hookflow.workflows.handlers.get_qstash_client")
    def test_publishes_message_with_sleep_step_delay(self, mock_get_client):
        """Test that sleep step delay is detected from completed_steps."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        completed_steps = {
            "step-1": "first_result",
            "sleep-step": {"slept_for": 60},
        }

        with override_settings(
            DJANGO_HOOKFLOW_DOMAIN="https://example.com",
            DJANGO_HOOKFLOW_WEBHOOK_PATH="/hookflow/",
        ):
            publish_next_step(
                workflow_id="test-workflow",
                run_id="test-run",
                data={},
                completed_steps=completed_steps,
            )

        call_kwargs = mock_client.publish_json.call_args.kwargs
        self.assertEqual(call_kwargs["delay"], "60s")

    @patch("django_hookflow.workflows.handlers.get_qstash_client")
    def test_handles_trailing_slash_in_domain(self, mock_get_client):
        """Test that trailing slash in domain is handled correctly."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        with override_settings(
            DJANGO_HOOKFLOW_DOMAIN="https://example.com/",
            DJANGO_HOOKFLOW_WEBHOOK_PATH="/hookflow/",
        ):
            publish_next_step(
                workflow_id="test-workflow",
                run_id="test-run",
                data={},
                completed_steps={},
            )

        call_kwargs = mock_client.publish_json.call_args.kwargs
        # Should not have double slashes
        self.assertEqual(
            call_kwargs["url"],
            "https://example.com/hookflow/workflow/test-workflow/",
        )

    @patch("django_hookflow.workflows.handlers.get_qstash_client")
    def test_raises_workflow_error_on_publish_failure(self, mock_get_client):
        """Test that WorkflowError is raised when QStash publish fails."""
        mock_client = MagicMock()
        mock_client.publish_json.side_effect = Exception("Network error")
        mock_get_client.return_value = mock_client

        with override_settings(
            DJANGO_HOOKFLOW_DOMAIN="https://example.com",
            DJANGO_HOOKFLOW_WEBHOOK_PATH="/hookflow/",
        ):
            with self.assertRaises(WorkflowError) as context:
                publish_next_step(
                    workflow_id="test-workflow",
                    run_id="test-run",
                    data={},
                    completed_steps={},
                )

            self.assertIn(
                "Failed to publish next step", str(context.exception)
            )
            self.assertIn("Network error", str(context.exception))

    @patch("django_hookflow.workflows.handlers.get_qstash_client")
    def test_payload_structure_is_correct(self, mock_get_client):
        """Test that payload structure includes all required fields."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        data = {"user_id": 123, "action": "process"}
        completed_steps = {"step-1": "result-1", "step-2": {"nested": "data"}}

        with override_settings(
            DJANGO_HOOKFLOW_DOMAIN="https://example.com",
            DJANGO_HOOKFLOW_WEBHOOK_PATH="/hookflow/",
        ):
            publish_next_step(
                workflow_id="my-workflow",
                run_id="my-run-id",
                data=data,
                completed_steps=completed_steps,
            )

        call_kwargs = mock_client.publish_json.call_args.kwargs
        payload = call_kwargs["body"]

        self.assertEqual(payload["workflow_id"], "my-workflow")
        self.assertEqual(payload["run_id"], "my-run-id")
        self.assertEqual(
            payload["data"], {"user_id": 123, "action": "process"}
        )
        self.assertEqual(
            payload["completed_steps"],
            {"step-1": "result-1", "step-2": {"nested": "data"}},
        )

    @patch("django_hookflow.workflows.handlers.get_qstash_client")
    def test_uses_default_webhook_path_when_not_configured(
        self, mock_get_client
    ):
        """Test that default webhook path is used when not configured."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        with override_settings(
            DJANGO_HOOKFLOW_DOMAIN="https://example.com",
        ):
            # Remove DJANGO_HOOKFLOW_WEBHOOK_PATH to use default
            publish_next_step(
                workflow_id="test-workflow",
                run_id="test-run",
                data={},
                completed_steps={},
            )

        call_kwargs = mock_client.publish_json.call_args.kwargs
        # Default path should be /hookflow/
        self.assertIn("/hookflow/workflow/test-workflow/", call_kwargs["url"])

    @patch("django_hookflow.workflows.handlers.get_qstash_client")
    def test_sleep_delay_overrides_explicit_delay_seconds(
        self, mock_get_client
    ):
        """Test that sleep step delay overrides explicit delay_seconds."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        completed_steps = {
            "sleep-step": {"slept_for": 120},
        }

        with override_settings(
            DJANGO_HOOKFLOW_DOMAIN="https://example.com",
            DJANGO_HOOKFLOW_WEBHOOK_PATH="/hookflow/",
        ):
            publish_next_step(
                workflow_id="test-workflow",
                run_id="test-run",
                data={},
                completed_steps=completed_steps,
                delay_seconds=30,  # This should be overridden by slept_for
            )

        call_kwargs = mock_client.publish_json.call_args.kwargs
        # Sleep delay (120s) should override explicit delay_seconds (30)
        self.assertEqual(call_kwargs["delay"], "120s")

    @patch("django_hookflow.workflows.handlers.get_qstash_client")
    def test_non_dict_last_step_result_uses_explicit_delay(
        self, mock_get_client
    ):
        """Test that non-dict last step uses explicit delay_seconds."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        completed_steps = {
            "step-1": "string_result",
        }

        with override_settings(
            DJANGO_HOOKFLOW_DOMAIN="https://example.com",
            DJANGO_HOOKFLOW_WEBHOOK_PATH="/hookflow/",
        ):
            publish_next_step(
                workflow_id="test-workflow",
                run_id="test-run",
                data={},
                completed_steps=completed_steps,
                delay_seconds=15,
            )

        call_kwargs = mock_client.publish_json.call_args.kwargs
        self.assertEqual(call_kwargs["delay"], "15s")

    @patch("django_hookflow.workflows.handlers.get_qstash_client")
    def test_dict_without_slept_for_uses_explicit_delay(self, mock_get_client):
        """Test that dict without slept_for uses explicit delay."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        completed_steps = {
            "step-1": {"result": "value", "other_key": 123},
        }

        with override_settings(
            DJANGO_HOOKFLOW_DOMAIN="https://example.com",
            DJANGO_HOOKFLOW_WEBHOOK_PATH="/hookflow/",
        ):
            publish_next_step(
                workflow_id="test-workflow",
                run_id="test-run",
                data={},
                completed_steps=completed_steps,
                delay_seconds=20,
            )

        call_kwargs = mock_client.publish_json.call_args.kwargs
        self.assertEqual(call_kwargs["delay"], "20s")


if __name__ == "__main__":
    unittest.main()
