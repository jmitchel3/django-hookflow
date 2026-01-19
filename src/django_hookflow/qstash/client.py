from __future__ import annotations

import json
from typing import Any

import requests
from django.conf import settings

from django_hookflow.exceptions import WorkflowError

QSTASH_API_URL = "https://qstash.upstash.io/v2/publish/"

_client_instance: QStashClient | None = None


class QStashClient:
    """
    Client for publishing messages to QStash.

    This provides a simple interface to publish JSON messages to QStash
    with support for delays and deduplication.
    """

    def __init__(self, token: str) -> None:
        """
        Initialize the QStash client.

        Args:
            token: The QStash API token (QSTASH_TOKEN)
        """
        self._token = token

    def publish_json(
        self,
        url: str,
        body: dict[str, Any],
        delay: str | None = None,
        deduplication_id: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Publish a JSON message to QStash.

        Args:
            url: The destination URL that QStash will call
            body: The JSON payload to send
            delay: Optional delay before delivery (e.g., "30s", "5m")
            deduplication_id: Optional ID to prevent duplicate messages
            headers: Optional custom headers to forward to the destination

        Returns:
            The QStash API response containing messageId

        Raises:
            WorkflowError: If the publish request fails
        """
        request_headers: dict[str, str] = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        if delay:
            request_headers["Upstash-Delay"] = delay

        if deduplication_id:
            request_headers["Upstash-Deduplication-Id"] = deduplication_id

        if headers:
            for key, value in headers.items():
                if key.lower() == "idempotency-key":
                    request_headers["Upstash-Deduplication-Id"] = value
                else:
                    request_headers[f"Upstash-Forward-{key}"] = value

        publish_url = f"{QSTASH_API_URL}{url}"

        try:
            response = requests.post(
                publish_url,
                data=json.dumps(body),
                headers=request_headers,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise WorkflowError(f"QStash publish failed: {e}") from e


def get_qstash_client() -> QStashClient:
    """
    Get the singleton QStash client instance.

    The client is lazily initialized using QSTASH_TOKEN from Django settings.

    Returns:
        The QStashClient instance

    Raises:
        WorkflowError: If QSTASH_TOKEN is not configured
    """
    global _client_instance

    if _client_instance is None:
        token = getattr(settings, "QSTASH_TOKEN", None)
        if not token:
            raise WorkflowError(
                "QSTASH_TOKEN is not configured in Django settings"
            )
        _client_instance = QStashClient(token)

    return _client_instance
