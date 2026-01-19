from __future__ import annotations

import hashlib
import time
import unittest
from unittest.mock import patch

import jwt
from django.test import RequestFactory
from django.test import override_settings

from django_hookflow.exceptions import WorkflowError
from django_hookflow.qstash.receiver import DEFAULT_CLOCK_SKEW_SECONDS
from django_hookflow.qstash.receiver import QStashReceiver
from django_hookflow.qstash.receiver import verify_qstash_signature


class TestClockSkewTolerance(unittest.TestCase):
    """Tests for clock skew tolerance in QStash signature verification."""

    def setUp(self):
        self.signing_key = "test-signing-key"
        self.receiver = QStashReceiver(
            current_signing_key=self.signing_key,
            next_signing_key=self.signing_key,
        )
        self.body = '{"test": "data"}'
        self.url = "https://example.com/webhook/"
        self.body_hash = hashlib.sha256(self.body.encode("utf-8")).hexdigest()

    def _create_token(
        self,
        exp_offset: int = 300,
        nbf_offset: int = 0,
    ) -> str:
        """Create a JWT token with specified exp/nbf offsets from now."""
        now = int(time.time())
        payload = {
            "iss": "Upstash",
            "sub": self.url,
            "exp": now + exp_offset,
            "nbf": now + nbf_offset,
            "body": self.body_hash,
        }
        return jwt.encode(payload, self.signing_key, algorithm="HS256")

    def test_verify_accepts_valid_token(self):
        """Test that a valid token is accepted."""
        token = self._create_token()
        claims = self.receiver.verify(
            signature=token,
            body=self.body,
            url=self.url,
        )
        self.assertEqual(claims["iss"], "Upstash")

    def test_verify_rejects_expired_token_without_leeway(self):
        """Test that expired token is rejected when clock_skew is 0."""
        # Token expired 10 seconds ago
        token = self._create_token(exp_offset=-10)
        with self.assertRaises(WorkflowError):
            self.receiver.verify(
                signature=token,
                body=self.body,
                url=self.url,
                clock_skew_seconds=0,
            )

    def test_verify_accepts_expired_token_with_leeway(self):
        """Test that slightly expired token is accepted with clock_skew."""
        # Token expired 30 seconds ago
        token = self._create_token(exp_offset=-30)
        # But with 60 second leeway, should still be valid
        claims = self.receiver.verify(
            signature=token,
            body=self.body,
            url=self.url,
            clock_skew_seconds=60,
        )
        self.assertEqual(claims["iss"], "Upstash")

    def test_verify_rejects_token_beyond_leeway(self):
        """Test that token expired beyond leeway is still rejected."""
        # Token expired 120 seconds ago
        token = self._create_token(exp_offset=-120)
        # With 60 second leeway, should still be rejected
        with self.assertRaises(WorkflowError):
            self.receiver.verify(
                signature=token,
                body=self.body,
                url=self.url,
                clock_skew_seconds=60,
            )

    def test_verify_accepts_future_nbf_within_leeway(self):
        """Test that nbf slightly in the future is accepted with leeway."""
        # Token not valid until 30 seconds from now
        token = self._create_token(nbf_offset=30)
        # But with 60 second leeway, should be accepted
        claims = self.receiver.verify(
            signature=token,
            body=self.body,
            url=self.url,
            clock_skew_seconds=60,
        )
        self.assertEqual(claims["iss"], "Upstash")

    def test_default_clock_skew_is_applied(self):
        """Test that default clock skew is used when not specified."""
        # Token expired just within default leeway (60 seconds)
        token = self._create_token(exp_offset=-50)
        claims = self.receiver.verify(
            signature=token,
            body=self.body,
            url=self.url,
            # clock_skew_seconds not specified - should use default
        )
        self.assertEqual(claims["iss"], "Upstash")

    @override_settings(DJANGO_HOOKFLOW_CLOCK_SKEW_SECONDS=120)
    def test_clock_skew_setting_is_used(self):
        """Test that DJANGO_HOOKFLOW_CLOCK_SKEW_SECONDS setting is used."""
        # Token expired 90 seconds ago
        token = self._create_token(exp_offset=-90)
        # Default is 60s, but setting is 120s
        claims = self.receiver.verify(
            signature=token,
            body=self.body,
            url=self.url,
        )
        self.assertEqual(claims["iss"], "Upstash")


class TestVerifyQStashSignatureClockSkew(unittest.TestCase):
    """Tests for verify_qstash_signature function clock skew handling."""

    def setUp(self):
        self.factory = RequestFactory()

    @patch("django_hookflow.qstash.receiver.settings")
    @patch("django_hookflow.qstash.receiver.QStashReceiver")
    def test_clock_skew_parameter_passed_to_receiver(
        self,
        mock_receiver_class,
        mock_settings,
    ):
        """Test that clock_skew_seconds is passed to receiver.verify()."""
        mock_receiver = mock_receiver_class.return_value
        mock_receiver.verify.return_value = {"iss": "Upstash"}
        mock_settings.QSTASH_CURRENT_SIGNING_KEY = "key1"
        mock_settings.QSTASH_NEXT_SIGNING_KEY = "key2"

        request = self.factory.post(
            "/webhook/",
            data='{"test": "data"}',
            content_type="application/json",
            HTTP_UPSTASH_SIGNATURE="test-signature",
        )

        verify_qstash_signature(request, clock_skew_seconds=120)

        call_kwargs = mock_receiver.verify.call_args.kwargs
        self.assertEqual(call_kwargs["clock_skew_seconds"], 120)


class TestDefaultClockSkewConstant(unittest.TestCase):
    """Tests for default clock skew constant."""

    def test_default_clock_skew_is_60_seconds(self):
        """Verify the default clock skew tolerance is 60 seconds."""
        self.assertEqual(DEFAULT_CLOCK_SKEW_SECONDS, 60)


if __name__ == "__main__":
    unittest.main()
