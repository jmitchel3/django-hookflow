from __future__ import annotations

import json
import logging
import traceback
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from django_hookflow.dlq import DeadLetterEntry
from django_hookflow.exceptions import StepCompleted
from django_hookflow.exceptions import WorkflowError
from django_hookflow.retry import get_retry_delay
from django_hookflow.retry import should_retry

from .handlers import publish_next_step
from .handlers import verify_qstash_signature
from .registry import get_workflow

logger = logging.getLogger(__name__)


def _is_persistence_enabled() -> bool:
    """Check if workflow persistence is enabled."""
    return getattr(settings, "DJANGO_HOOKFLOW_PERSISTENCE_ENABLED", False)


def _get_persistence():
    """Lazy import of WorkflowPersistence to avoid circular imports."""
    from django_hookflow.persistence import WorkflowPersistence

    return WorkflowPersistence


@csrf_exempt
@require_POST
def workflow_webhook(request: HttpRequest, workflow_id: str) -> HttpResponse:
    """
    Webhook endpoint for workflow execution.

    This view handles incoming QStash webhook calls for workflow execution.
    It verifies the signature, parses the state, executes the workflow,
    and schedules the next step if needed.

    Args:
        request: The Django HTTP request
        workflow_id: The workflow ID from the URL

    Returns:
        HttpResponse with status and result information
    """
    # 1. Verify QStash signature
    try:
        verify_qstash_signature(request)
    except WorkflowError as e:
        logger.warning("QStash signature verification failed: %s", e)
        return JsonResponse(
            {"error": "Signature verification failed", "detail": str(e)},
            status=401,
        )

    # 2. Parse the request body
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        logger.exception("Failed to parse workflow payload")
        return JsonResponse(
            {"error": "Invalid JSON payload"},
            status=400,
        )

    # 3. Extract state from payload
    payload_workflow_id = payload.get("workflow_id")
    run_id = payload.get("run_id")
    data = payload.get("data", {})
    completed_steps: dict[str, Any] = payload.get("completed_steps", {})

    # 3a. Optionally load/merge completed steps from database
    if _is_persistence_enabled() and run_id:
        db_completed_steps = _get_persistence().get_completed_steps(run_id)
        # Merge DB steps with payload steps (payload takes precedence)
        merged_steps = {**db_completed_steps, **completed_steps}
        completed_steps = merged_steps

    # Validate payload
    if not payload_workflow_id or payload_workflow_id != workflow_id:
        logger.error(
            "Workflow ID mismatch: URL=%s, payload=%s",
            workflow_id,
            payload_workflow_id,
        )
        return JsonResponse(
            {"error": "Workflow ID mismatch"},
            status=400,
        )

    if not run_id:
        logger.error("Missing run_id in workflow payload")
        return JsonResponse(
            {"error": "Missing run_id"},
            status=400,
        )

    # 4. Get the workflow from registry
    workflow = get_workflow(workflow_id)
    if workflow is None:
        logger.error("Workflow not found: %s", workflow_id)
        return JsonResponse(
            {"error": f"Workflow '{workflow_id}' not found"},
            status=404,
        )

    # 5. Execute the workflow
    try:
        result = workflow.execute(
            data=data,
            run_id=run_id,
            completed_steps=completed_steps,
        )

        # Workflow completed successfully (no more steps)
        logger.info(
            "Workflow completed: workflow_id=%s, run_id=%s",
            workflow_id,
            run_id,
        )

        # Persist workflow completion
        if _is_persistence_enabled():
            _get_persistence().mark_completed(run_id, result)

        return JsonResponse(
            {
                "status": "completed",
                "workflow_id": workflow_id,
                "run_id": run_id,
                "result": result,
            }
        )

    except StepCompleted as e:
        # Step completed - schedule next invocation
        logger.info(
            "Step completed: workflow_id=%s, run_id=%s, step_id=%s",
            workflow_id,
            run_id,
            e.step_id,
        )

        # Persist step result
        if _is_persistence_enabled():
            _get_persistence().save_step(run_id, e.step_id, e.result)

        try:
            publish_next_step(
                workflow_id=workflow_id,
                run_id=run_id,
                data=data,
                completed_steps=e.completed_steps,
            )
        except WorkflowError as publish_err:
            logger.exception("Failed to schedule next step")
            return JsonResponse(
                {
                    "error": "Failed to schedule next step",
                    "detail": str(publish_err),
                },
                status=500,
            )

        return JsonResponse(
            {
                "status": "step_completed",
                "workflow_id": workflow_id,
                "run_id": run_id,
                "step_id": e.step_id,
                "completed_steps": list(e.completed_steps.keys()),
            }
        )

    except WorkflowError as wf_err:
        # Workflow error (step failure, etc.)
        logger.exception(
            "Workflow error: workflow_id=%s, run_id=%s",
            workflow_id,
            run_id,
        )

        # Extract current attempt from payload (default 0)
        attempt = payload.get("attempt", 0)

        # Check if we should retry
        if should_retry(attempt):
            # Schedule retry with exponential backoff
            retry_delay = get_retry_delay(attempt)
            logger.info(
                "Scheduling retry: workflow=%s, run=%s, attempt=%d, delay=%ds",
                workflow_id,
                run_id,
                attempt + 1,
                retry_delay,
            )

            try:
                publish_next_step(
                    workflow_id=workflow_id,
                    run_id=run_id,
                    data=data,
                    completed_steps=completed_steps,
                    delay_seconds=retry_delay,
                    attempt=attempt + 1,
                )
                return JsonResponse(
                    {
                        "status": "retrying",
                        "workflow_id": workflow_id,
                        "run_id": run_id,
                        "attempt": attempt + 1,
                        "retry_delay": retry_delay,
                        "error": str(wf_err),
                    }
                )
            except WorkflowError:
                logger.exception("Failed to schedule retry")
                # Fall through to DLQ if retry scheduling fails

        # Max retries exceeded or retry scheduling failed - add to DLQ
        logger.warning(
            "Adding to DLQ: workflow_id=%s, run_id=%s, attempts=%d",
            workflow_id,
            run_id,
            attempt + 1,
        )

        error_tb = traceback.format_exc()
        DeadLetterEntry.add_entry(
            workflow_id=workflow_id,
            run_id=run_id,
            payload=payload,
            error_message=str(wf_err),
            error_traceback=error_tb,
            attempt_count=attempt + 1,
        )

        # Persist workflow failure
        if _is_persistence_enabled():
            _get_persistence().mark_failed(run_id, str(wf_err))

        return JsonResponse(
            {
                "error": "Workflow execution failed",
                "detail": str(wf_err),
                "workflow_id": workflow_id,
                "run_id": run_id,
                "added_to_dlq": True,
            },
            status=500,
        )

    except Exception as exc:
        # Unexpected error
        logger.exception(
            "Unexpected error in workflow: workflow_id=%s, run_id=%s",
            workflow_id,
            run_id,
        )

        # Persist workflow failure
        if _is_persistence_enabled():
            _get_persistence().mark_failed(run_id, f"Unexpected error: {exc}")

        return JsonResponse(
            {
                "error": "Internal server error",
                "workflow_id": workflow_id,
                "run_id": run_id,
            },
            status=500,
        )
