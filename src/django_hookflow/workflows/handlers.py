from __future__ import annotations

from typing import Any

from django.conf import settings
from django.http import HttpRequest
from qstash import Receiver

from django_hookflow.exceptions import WorkflowError


def verify_qstash_signature(request: HttpRequest) -> bool:
    """
    Verify that a request came from QStash.

    This uses the QStash Receiver to verify the signature header
    against the configured signing keys.

    Args:
        request: The Django HTTP request to verify

    Returns:
        True if the signature is valid

    Raises:
        WorkflowError: If verification fails or keys not configured
    """
    current_signing_key = getattr(settings, "QSTASH_CURRENT_SIGNING_KEY", None)
    next_signing_key = getattr(settings, "QSTASH_NEXT_SIGNING_KEY", None)

    if not current_signing_key or not next_signing_key:
        raise WorkflowError(
            "QSTASH_CURRENT_SIGNING_KEY and QSTASH_NEXT_SIGNING_KEY "
            "must be set in Django settings"
        )

    receiver = Receiver(
        current_signing_key=current_signing_key,
        next_signing_key=next_signing_key,
    )

    # Get the signature from headers
    signature = request.headers.get("Upstash-Signature")
    if not signature:
        raise WorkflowError("Missing Upstash-Signature header")

    # Get the request body
    body = request.body.decode("utf-8")

    # Build the full URL for verification
    url = request.build_absolute_uri()

    try:
        receiver.verify(
            body=body,
            signature=signature,
            url=url,
        )
        return True
    except Exception as e:
        msg = f"QStash signature verification failed: {e}"
        raise WorkflowError(msg) from e


def publish_next_step(
    workflow_id: str,
    run_id: str,
    data: dict[str, Any],
    completed_steps: dict[str, Any],
    delay_seconds: int = 0,
) -> None:
    """
    Publish the next step invocation to QStash.

    This schedules the next workflow invocation with the updated state
    (including newly completed steps).

    Args:
        workflow_id: The workflow's unique identifier
        run_id: The unique run identifier
        data: The original workflow payload
        completed_steps: All completed step results so far
        delay_seconds: Optional delay before executing the next step

    Raises:
        WorkflowError: If publishing fails
    """
    from qstash import QStash

    qstash_token = getattr(settings, "QSTASH_TOKEN", None)
    if not qstash_token:
        raise WorkflowError("QSTASH_TOKEN is not set in Django settings")

    domain = getattr(settings, "DJANGO_HOOKFLOW_DOMAIN", None)
    if not domain:
        msg = "DJANGO_HOOKFLOW_DOMAIN is not set in Django settings"
        raise WorkflowError(msg)

    webhook_path = getattr(
        settings, "DJANGO_HOOKFLOW_WEBHOOK_PATH", "/hookflow/"
    )

    # Build the webhook URL
    base_url = domain.rstrip("/")
    webhook_url = f"{base_url}{webhook_path}workflow/{workflow_id}/"

    # Prepare the payload with updated state
    payload = {
        "workflow_id": workflow_id,
        "run_id": run_id,
        "data": data,
        "completed_steps": completed_steps,
    }

    try:
        client = QStash(token=qstash_token)

        # Check if there's a sleep delay from the last step
        last_step_result = None
        if completed_steps:
            # Get the most recently completed step
            last_step_id = list(completed_steps.keys())[-1]
            last_step_result = completed_steps[last_step_id]

        # Determine delay from sleep step
        actual_delay = delay_seconds
        is_sleep = isinstance(last_step_result, dict)
        if is_sleep and "slept_for" in last_step_result:
            actual_delay = last_step_result["slept_for"]

        if actual_delay > 0:
            client.message.publish_json(
                url=webhook_url,
                body=payload,
                delay=f"{actual_delay}s",
            )
        else:
            client.message.publish_json(
                url=webhook_url,
                body=payload,
            )

    except Exception as e:
        raise WorkflowError(f"Failed to publish next step: {e}") from e
