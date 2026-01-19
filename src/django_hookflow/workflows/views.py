from __future__ import annotations

import json
import logging
from typing import Any

from django.http import HttpRequest
from django.http import HttpResponse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from django_hookflow.exceptions import StepCompleted
from django_hookflow.exceptions import WorkflowError

from .handlers import publish_next_step
from .handlers import verify_qstash_signature
from .registry import get_workflow

logger = logging.getLogger(__name__)


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
        return JsonResponse(
            {
                "error": "Workflow execution failed",
                "detail": str(wf_err),
                "workflow_id": workflow_id,
                "run_id": run_id,
            },
            status=500,
        )

    except Exception:
        # Unexpected error
        logger.exception(
            "Unexpected error in workflow: workflow_id=%s, run_id=%s",
            workflow_id,
            run_id,
        )
        return JsonResponse(
            {
                "error": "Internal server error",
                "workflow_id": workflow_id,
                "run_id": run_id,
            },
            status=500,
        )
