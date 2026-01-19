from __future__ import annotations

from typing import Any

from django.conf import settings
from django.http import HttpRequest

from django_hookflow.exceptions import WorkflowError
from django_hookflow.qstash import get_qstash_client
from django_hookflow.qstash import verify_qstash_signature as _verify_signature


def verify_qstash_signature(request: HttpRequest) -> bool:
    """
    Verify that a request came from QStash.

    This verifies the JWT signature in the Upstash-Signature header
    against the configured signing keys.

    Args:
        request: The Django HTTP request to verify

    Returns:
        True if the signature is valid

    Raises:
        WorkflowError: If verification fails or keys not configured
    """
    return _verify_signature(request)


def _generate_idempotency_key(
    run_id: str,
    completed_steps: dict[str, Any],
    attempt: int = 0,
) -> str:
    """
    Generate an idempotency key for QStash messages.

    The key is based on run_id, the number of completed steps, and attempt
    number to ensure each message is unique and prevent duplicate processing.

    Args:
        run_id: The unique run identifier
        completed_steps: Current completed steps dictionary
        attempt: The retry attempt number

    Returns:
        A unique idempotency key string
    """
    step_count = len(completed_steps)
    return f"{run_id}:step:{step_count}:attempt:{attempt}"


def publish_next_step(
    workflow_id: str,
    run_id: str,
    data: dict[str, Any],
    completed_steps: dict[str, Any],
    delay_seconds: int = 0,
    attempt: int = 0,
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
        attempt: The current retry attempt number (0 for first attempt)

    Raises:
        WorkflowError: If publishing fails
    """
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
        "attempt": attempt,
    }

    try:
        # Generate idempotency key to prevent duplicate processing
        idempotency_key = _generate_idempotency_key(
            run_id=run_id,
            completed_steps=completed_steps,
            attempt=attempt,
        )

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

        # Get the QStash client
        client = get_qstash_client()

        if actual_delay > 0:
            client.publish_json(
                url=webhook_url,
                body=payload,
                delay=f"{actual_delay}s",
                deduplication_id=idempotency_key,
            )
        else:
            client.publish_json(
                url=webhook_url,
                body=payload,
                deduplication_id=idempotency_key,
            )

    except Exception as e:
        raise WorkflowError(f"Failed to publish next step: {e}") from e
