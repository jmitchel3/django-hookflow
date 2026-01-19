from __future__ import annotations

import hashlib
from typing import Any

import jwt
from django.conf import settings
from django.http import HttpRequest

from django_hookflow.exceptions import WorkflowError

# Default clock skew tolerance in seconds
DEFAULT_CLOCK_SKEW_SECONDS = 60


class QStashReceiver:
    """
    Receiver for verifying QStash webhook signatures.

    QStash signs requests with a JWT token that can be verified using
    the signing keys from the Upstash console.
    """

    def __init__(
        self,
        current_signing_key: str,
        next_signing_key: str,
    ) -> None:
        """
        Initialize the QStash receiver.

        Args:
            current_signing_key: The current signing key from QStash console
            next_signing_key: The next signing key for key rotation
        """
        self._current_key = current_signing_key
        self._next_key = next_signing_key

    def verify(
        self,
        signature: str,
        body: str,
        url: str,
        clock_skew_seconds: int | None = None,
    ) -> dict[str, Any]:
        """
        Verify a QStash webhook signature.

        Args:
            signature: The Upstash-Signature header value (JWT token)
            body: The raw request body as a string
            url: The full URL of the webhook endpoint
            clock_skew_seconds: Tolerance for clock skew between servers.
                Used as leeway for JWT exp/nbf validation. Defaults to
                DJANGO_HOOKFLOW_CLOCK_SKEW_SECONDS setting or 60 seconds.

        Returns:
            The decoded JWT claims if verification succeeds

        Raises:
            WorkflowError: If signature verification fails
        """
        if clock_skew_seconds is None:
            clock_skew_seconds = getattr(
                settings,
                "DJANGO_HOOKFLOW_CLOCK_SKEW_SECONDS",
                DEFAULT_CLOCK_SKEW_SECONDS,
            )

        keys = [self._current_key, self._next_key]

        for key in keys:
            try:
                claims = jwt.decode(
                    signature,
                    key,
                    algorithms=["HS256"],
                    options={
                        "require": ["iss", "sub", "exp", "nbf", "body"],
                    },
                    leeway=clock_skew_seconds,
                )

                if claims.get("iss") != "Upstash":
                    continue

                if claims.get("sub") != url:
                    continue

                expected_body_hash = hashlib.sha256(
                    body.encode("utf-8")
                ).hexdigest()
                if claims.get("body") != expected_body_hash:
                    continue

                return claims

            except jwt.ExpiredSignatureError:
                continue
            except jwt.InvalidTokenError:
                continue

        raise WorkflowError(
            "QStash signature verification failed: "
            "invalid signature or claims"
        )


def verify_qstash_signature(
    request: HttpRequest,
    clock_skew_seconds: int | None = None,
) -> bool:
    """
    Verify that a request came from QStash.

    This verifies the JWT signature in the Upstash-Signature header
    against the configured signing keys.

    Args:
        request: The Django HTTP request to verify
        clock_skew_seconds: Tolerance for clock skew between servers.
            Used as leeway for JWT exp/nbf validation. Defaults to
            DJANGO_HOOKFLOW_CLOCK_SKEW_SECONDS setting or 60 seconds.

    Returns:
        True if the signature is valid

    Raises:
        WorkflowError: If verification fails or keys not configured
    """
    current_key = getattr(settings, "QSTASH_CURRENT_SIGNING_KEY", None)
    next_key = getattr(settings, "QSTASH_NEXT_SIGNING_KEY", None)

    if not current_key or not next_key:
        raise WorkflowError(
            "QStash signing keys not configured. "
            "Set QSTASH_CURRENT_SIGNING_KEY and QSTASH_NEXT_SIGNING_KEY."
        )

    body = request.body.decode("utf-8")
    signature = request.headers.get("Upstash-Signature", "")
    url = request.build_absolute_uri()

    if not signature:
        raise WorkflowError(
            "QStash signature verification failed: "
            "missing Upstash-Signature header"
        )

    receiver = QStashReceiver(current_key, next_key)
    receiver.verify(
        signature=signature,
        body=body,
        url=url,
        clock_skew_seconds=clock_skew_seconds,
    )
    return True
