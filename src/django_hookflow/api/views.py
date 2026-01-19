from __future__ import annotations

from typing import Any

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from django_hookflow.models import StepExecution
from django_hookflow.models import WorkflowRun
from django_hookflow.workflows.registry import get_all_workflows


def serialize_step(step: StepExecution) -> dict[str, Any]:
    """Serialize a StepExecution model to a dictionary."""
    return {
        "step_id": step.step_id,
        "status": step.status,
        "result": step.result,
        "error_message": step.error_message,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "completed_at": (
            step.completed_at.isoformat() if step.completed_at else None
        ),
    }


def serialize_workflow_run(run: WorkflowRun) -> dict[str, Any]:
    """Serialize a WorkflowRun model to a dictionary."""
    steps = [
        serialize_step(step) for step in run.steps.all().order_by("started_at")
    ]
    return {
        "run_id": run.run_id,
        "workflow_id": run.workflow_id,
        "status": run.status,
        "data": run.data,
        "result": run.result,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "completed_at": (
            run.completed_at.isoformat() if run.completed_at else None
        ),
        "steps": steps,
    }


@require_GET
def workflow_status(request, run_id: str) -> JsonResponse:
    """
    Get the status of a single workflow run by run_id.

    Returns:
        JsonResponse with workflow run details or 404 if not found.
    """
    try:
        run = WorkflowRun.objects.get(run_id=run_id)
    except WorkflowRun.DoesNotExist:
        return JsonResponse(
            {"error": "Workflow run not found", "run_id": run_id},
            status=404,
        )

    return JsonResponse(serialize_workflow_run(run))


@require_GET
def workflow_list(request) -> JsonResponse:
    """
    List workflow runs with optional filtering.

    Query parameters:
        - workflow_id: Filter by workflow ID
        - status: Filter by status (pending, running, completed, failed)
        - limit: Maximum number of results (default 50)
        - offset: Number of results to skip (default 0)

    Returns:
        JsonResponse with total, pagination info, and workflow runs.
    """
    workflow_id = request.GET.get("workflow_id")
    status = request.GET.get("status")

    try:
        limit = int(request.GET.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50

    try:
        offset = int(request.GET.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0

    # Build queryset with filters
    queryset = WorkflowRun.objects.all()

    if workflow_id:
        queryset = queryset.filter(workflow_id=workflow_id)

    if status:
        queryset = queryset.filter(status=status)

    # Get total count before pagination
    total = queryset.count()

    # Apply pagination and ordering
    runs = queryset.order_by("-created_at")[
        offset : offset + limit  # noqa: E203
    ]

    return JsonResponse(
        {
            "total": total,
            "limit": limit,
            "offset": offset,
            "runs": [serialize_workflow_run(run) for run in runs],
        }
    )


@require_GET
def workflow_types(request) -> JsonResponse:
    """
    List all registered workflow types.

    Returns:
        JsonResponse with list of workflow IDs from the registry.
    """
    workflows = get_all_workflows()
    workflow_ids = list(workflows.keys())

    return JsonResponse(
        {
            "workflows": workflow_ids,
            "count": len(workflow_ids),
        }
    )
