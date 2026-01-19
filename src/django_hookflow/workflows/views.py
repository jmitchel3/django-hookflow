from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.utils import DatabaseError
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from django_hookflow.dlq import DeadLetterEntry
from django_hookflow.exceptions import ExecutionTimeoutError
from django_hookflow.exceptions import StepCompleted
from django_hookflow.exceptions import WorkflowError
from django_hookflow.retry import get_retry_delay
from django_hookflow.retry import is_retryable_error
from django_hookflow.retry import should_retry
from django_hookflow.shutdown import get_shutdown_manager

from .handlers import publish_next_step
from .handlers import verify_qstash_signature
from .registry import get_workflow

try:
    from django_ratelimit.decorators import (
        ratelimit,  # type: ignore[import-not-found]
    )
except Exception:  # pragma: no cover - optional dependency
    ratelimit = None

logger = logging.getLogger(__name__)

# Default number of publish retry attempts
DEFAULT_MAX_PUBLISH_FAILURES = 3

# Default execution timeout in seconds
DEFAULT_EXECUTION_TIMEOUT = 30


def _get_max_publish_failures() -> int:
    """Get the maximum number of publish retry attempts."""
    return getattr(
        settings,
        "DJANGO_HOOKFLOW_MAX_PUBLISH_FAILURES",
        DEFAULT_MAX_PUBLISH_FAILURES,
    )


def _get_execution_timeout() -> int:
    """Get the execution timeout in seconds."""
    return getattr(
        settings,
        "DJANGO_HOOKFLOW_EXECUTION_TIMEOUT",
        DEFAULT_EXECUTION_TIMEOUT,
    )


class _TimeoutFlag:
    """Thread-safe flag for cooperative timeout checking."""

    def __init__(self) -> None:
        self._timed_out = False
        self._lock = threading.Lock()

    def set_timed_out(self) -> None:
        with self._lock:
            self._timed_out = True

    def is_timed_out(self) -> bool:
        with self._lock:
            return self._timed_out


@contextmanager
def _execution_timeout(
    timeout_seconds: int,
    workflow_id: str,
    run_id: str,
) -> Generator[_TimeoutFlag]:
    """
    Context manager for cooperative execution timeout.

    This uses a threading-based approach that sets a flag when the timeout
    expires. The workflow code should periodically check this flag via the
    returned TimeoutFlag object.

    Note: This is a cooperative timeout - it will not interrupt blocking I/O
    operations. It relies on the workflow checking the flag or completing
    steps within the timeout period.

    Args:
        timeout_seconds: Maximum execution time in seconds
        workflow_id: The workflow identifier (for error messages)
        run_id: The run identifier (for error messages)

    Yields:
        TimeoutFlag object that can be checked for timeout status

    Raises:
        ExecutionTimeoutError: If the timeout expires before context exits
    """
    flag = _TimeoutFlag()
    timer: threading.Timer | None = None

    def _on_timeout() -> None:
        flag.set_timed_out()
        logger.warning(
            "Execution timeout triggered: workflow_id=%s, run_id=%s, "
            "timeout=%ds",
            workflow_id,
            run_id,
            timeout_seconds,
        )

    if timeout_seconds > 0:
        timer = threading.Timer(timeout_seconds, _on_timeout)
        timer.daemon = True
        timer.start()

    try:
        yield flag
        # Check if we timed out during execution
        if flag.is_timed_out():
            raise ExecutionTimeoutError(
                f"Workflow execution exceeded timeout of {timeout_seconds}s",
                timeout_seconds=timeout_seconds,
                workflow_id=workflow_id,
                run_id=run_id,
            )
    finally:
        if timer is not None:
            timer.cancel()


def _publish_with_retry(
    workflow_id: str,
    run_id: str,
    data: dict,
    completed_steps: dict,
    delay_seconds: int | None = None,
    attempt: int = 0,
) -> bool:
    """
    Publish next step with retry logic.

    Attempts to publish the next step up to MAX_PUBLISH_FAILURES times
    with exponential backoff between attempts.

    Args:
        workflow_id: The workflow identifier
        run_id: The unique run identifier
        data: The workflow payload data
        completed_steps: Completed step results
        delay_seconds: Optional delay before delivery
        attempt: Current retry attempt (for workflow retries)

    Returns:
        True if publish succeeded, False if all attempts failed
    """
    max_attempts = _get_max_publish_failures()
    last_error: Exception | None = None

    for publish_attempt in range(max_attempts):
        try:
            publish_next_step(
                workflow_id=workflow_id,
                run_id=run_id,
                data=data,
                completed_steps=completed_steps,
                delay_seconds=delay_seconds,
                attempt=attempt,
            )
            if publish_attempt > 0:
                logger.info(
                    "Publish succeeded after %d retries: workflow_id=%s, "
                    "run_id=%s",
                    publish_attempt,
                    workflow_id,
                    run_id,
                )
            return True
        except Exception as e:
            last_error = e
            if publish_attempt < max_attempts - 1:
                # Exponential backoff: 0.1s, 0.2s, 0.4s
                backoff = 0.1 * (2**publish_attempt)
                logger.warning(
                    "Publish attempt %d/%d failed, retrying in %.1fs: "
                    "workflow_id=%s, run_id=%s, error=%s",
                    publish_attempt + 1,
                    max_attempts,
                    backoff,
                    workflow_id,
                    run_id,
                    e,
                )
                time.sleep(backoff)

    logger.error(
        "All %d publish attempts failed: workflow_id=%s, run_id=%s, "
        "last_error=%s",
        max_attempts,
        workflow_id,
        run_id,
        last_error,
    )
    return False


_RATE_LIMIT_SENTINEL = object()


def _rate_limit_rate(request: HttpRequest) -> str:
    return getattr(settings, "DJANGO_HOOKFLOW_RATE_LIMIT", "100/minute")


def _apply_rate_limit(view_func):
    rate_setting = getattr(
        settings,
        "DJANGO_HOOKFLOW_RATE_LIMIT",
        _RATE_LIMIT_SENTINEL,
    )
    if rate_setting in (None, ""):
        return view_func
    if ratelimit is None:
        if rate_setting is not _RATE_LIMIT_SENTINEL:
            logger.warning(
                "DJANGO_HOOKFLOW_RATE_LIMIT is set but django-ratelimit "
                "is not installed"
            )
        return view_func

    return ratelimit(key="ip", rate=_rate_limit_rate, block=True)(view_func)


def _is_persistence_enabled() -> bool:
    """Check if workflow persistence is enabled."""
    return getattr(settings, "DJANGO_HOOKFLOW_PERSISTENCE_ENABLED", True)


def _get_persistence():
    """Lazy import of WorkflowPersistence to avoid circular imports."""
    from django_hookflow.persistence import WorkflowPersistence

    return WorkflowPersistence


def _acquire_workflow_lock(run_id: str) -> bool:
    """
    Acquire a lock on the workflow run to prevent concurrent execution.

    Uses select_for_update with nowait to prevent blocking.

    Args:
        run_id: The workflow run identifier

    Returns:
        True if lock acquired, False if already locked or not found
    """
    if not _is_persistence_enabled():
        return True

    from django_hookflow.models import WorkflowRun

    try:
        with transaction.atomic():
            WorkflowRun.objects.select_for_update(nowait=True).get(
                run_id=run_id
            )
            return True
    except WorkflowRun.DoesNotExist:
        return True
    except DatabaseError:
        return False


def _safe_persist_step(run_id: str, step_id: str, result: Any) -> None:
    """
    Safely persist step result, logging errors but not failing.

    This ensures that persistence failures don't block workflow execution.
    """
    if not _is_persistence_enabled():
        return

    try:
        _get_persistence().save_step(run_id, step_id, result)
    except Exception as e:
        logger.exception(
            "Failed to persist step (workflow will continue): "
            "run_id=%s, step_id=%s, error=%s",
            run_id,
            step_id,
            e,
        )


def _safe_persist_completion(run_id: str, result: Any) -> None:
    """
    Safely persist workflow completion, logging errors but not failing.
    """
    if not _is_persistence_enabled():
        return

    try:
        _get_persistence().mark_completed(run_id, result)
    except Exception as e:
        logger.exception(
            "Failed to persist workflow completion: run_id=%s, error=%s",
            run_id,
            e,
        )


def _safe_persist_failure(run_id: str, error_message: str) -> None:
    """
    Safely persist workflow failure, logging errors but not failing.
    """
    if not _is_persistence_enabled():
        return

    try:
        _get_persistence().mark_failed(run_id, error_message)
    except Exception as e:
        logger.exception(
            "Failed to persist workflow failure: run_id=%s, error=%s",
            run_id,
            e,
        )


def _workflow_webhook_impl(
    request: HttpRequest,
    workflow_id: str,
) -> HttpResponse:
    """
    Webhook endpoint for workflow execution.

    This view handles incoming QStash webhook calls for workflow execution.
    It verifies the signature, parses the state, executes the workflow,
    and schedules the next step if needed.

    Idempotency Guarantees:
        This endpoint provides idempotency through multiple mechanisms:

        1. **Lock-based deduplication**: Uses SELECT FOR UPDATE (nowait) to
           prevent concurrent execution of the same workflow run. If a request
           arrives while another is processing, it receives a 409 response and
           the message will be retried by QStash.

        2. **Step result caching**: Completed step results are stored in the
           database and merged with incoming payload. If QStash retries a
           message after a step completed, the cached result is used instead
           of re-executing the step.

        3. **Completed steps comparison**: When DB steps are merged with
           payload steps, duplicates are detected and logged for monitoring.

    Args:
        request: The Django HTTP request
        workflow_id: The workflow ID from the URL

    Returns:
        HttpResponse with status and result information
    """
    # 1. Verify QStash signature
    try:
        verify_qstash_signature(request)
    except WorkflowError:
        logger.warning(
            "QStash signature verification failed for %s", workflow_id
        )
        return JsonResponse(
            {"error": "Signature verification failed"},
            status=401,
        )

    # 2. Enforce payload size limit
    max_payload_size = getattr(
        settings,
        "DJANGO_HOOKFLOW_MAX_PAYLOAD_SIZE",
        1024 * 1024,
    )
    payload_bytes = request.body
    if payload_bytes is not None and len(payload_bytes) > max_payload_size:
        logger.warning(
            "Payload too large: workflow_id=%s, size=%d, limit=%d",
            workflow_id,
            len(payload_bytes),
            max_payload_size,
        )
        return JsonResponse(
            {"error": "Payload too large"},
            status=413,
        )

    # 3. Parse the request body
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
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
        if db_completed_steps:
            # Check for steps that exist in both DB and payload (idempotency)
            duplicate_steps = set(db_completed_steps.keys()) & set(
                completed_steps.keys()
            )
            if duplicate_steps:
                logger.info(
                    "Idempotency: detected %d duplicate step(s) in payload "
                    "(using cached results): workflow_id=%s, run_id=%s, "
                    "duplicate_steps=%s",
                    len(duplicate_steps),
                    workflow_id,
                    run_id,
                    list(duplicate_steps),
                )
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

    # 3b. Check if shutdown is in progress
    shutdown_manager = get_shutdown_manager()
    if shutdown_manager.is_shutting_down:
        logger.info(
            "Rejecting request during shutdown: workflow_id=%s, run_id=%s",
            workflow_id,
            run_id,
        )
        return JsonResponse(
            {"error": "Service is shutting down"},
            status=503,
        )

    # 4. Get the workflow from registry
    workflow = get_workflow(workflow_id)
    if workflow is None:
        logger.error("Workflow not found: %s", workflow_id)
        return JsonResponse(
            {"error": "Workflow not found"},
            status=404,
        )

    # 4a. Try to acquire lock to prevent concurrent execution
    if not _acquire_workflow_lock(run_id):
        logger.info(
            "Idempotency: lock contention rejected duplicate request "
            "(another execution in progress): workflow_id=%s, run_id=%s",
            workflow_id,
            run_id,
        )
        return JsonResponse(
            {"error": "Workflow execution in progress"},
            status=409,
        )

    # 5. Execute the workflow with timeout
    # Per-workflow timeout takes precedence over global setting
    workflow_timeout = getattr(workflow, "timeout", None)
    if workflow_timeout is not None:
        timeout_seconds = workflow_timeout
    else:
        timeout_seconds = _get_execution_timeout()

    # Track request for graceful shutdown
    shutdown_manager.track_request_start(run_id)
    try:
        with _execution_timeout(timeout_seconds, workflow_id, run_id):
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

        # Persist workflow completion (non-blocking)
        _safe_persist_completion(run_id, result)

        return JsonResponse(
            {
                "status": "completed",
                "workflow_id": workflow_id,
                "run_id": run_id,
                "result": result,
            }
        )

    except ExecutionTimeoutError as timeout_err:
        # Execution timeout - treat as retryable error
        logger.warning(
            "Workflow execution timed out: workflow_id=%s, run_id=%s, "
            "timeout=%ds",
            workflow_id,
            run_id,
            timeout_seconds,
        )

        # Extract current attempt from payload
        attempt = payload.get("attempt", 0)

        # Try to schedule a retry
        if should_retry(attempt):
            retry_delay = get_retry_delay(attempt)
            if _publish_with_retry(
                workflow_id=workflow_id,
                run_id=run_id,
                data=data,
                completed_steps=completed_steps,
                delay_seconds=retry_delay,
                attempt=attempt + 1,
            ):
                return JsonResponse(
                    {
                        "status": "retrying",
                        "workflow_id": workflow_id,
                        "run_id": run_id,
                        "reason": "execution_timeout",
                        "attempt": attempt + 1,
                        "retry_delay": retry_delay,
                    }
                )

        # Add to DLQ if not retryable or retry failed
        error_tb = traceback.format_exc()
        DeadLetterEntry.add_entry(
            workflow_id=workflow_id,
            run_id=run_id,
            payload=payload,
            error_message=str(timeout_err),
            error_traceback=error_tb,
            attempt_count=attempt + 1,
            completed_steps=completed_steps,
        )

        _safe_persist_failure(run_id, str(timeout_err))

        return JsonResponse(
            {
                "error": "Workflow execution timed out",
                "workflow_id": workflow_id,
                "run_id": run_id,
                "timeout_seconds": timeout_seconds,
                "added_to_dlq": True,
            },
            status=504,
        )

    except StepCompleted as e:
        # Step completed - schedule next invocation
        logger.info(
            "Step completed: workflow_id=%s, run_id=%s, step_id=%s",
            workflow_id,
            run_id,
            e.step_id,
        )

        # Persist step result BEFORE publishing (ensures durability)
        _safe_persist_step(run_id, e.step_id, e.result)

        # Reset retry counter on successful step completion
        if _is_persistence_enabled():
            try:
                _get_persistence().reset_retry_attempt(run_id)
            except Exception as reset_err:
                logger.warning(
                    "Failed to reset retry attempt: run_id=%s, error=%s",
                    run_id,
                    reset_err,
                )

        # Publish with retry logic
        if not _publish_with_retry(
            workflow_id=workflow_id,
            run_id=run_id,
            data=data,
            completed_steps=e.completed_steps,
        ):
            return JsonResponse(
                {"error": "Failed to schedule next step after retries"},
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

        # Check if error is retryable and we should retry
        if is_retryable_error(wf_err) and should_retry(attempt):
            # Schedule retry with exponential backoff
            retry_delay = get_retry_delay(attempt)
            logger.info(
                "Scheduling retry: workflow=%s, run=%s, attempt=%d, delay=%ds",
                workflow_id,
                run_id,
                attempt + 1,
                retry_delay,
            )

            # Increment retry attempt in DB before publishing
            if _is_persistence_enabled():
                try:
                    _get_persistence().increment_retry_attempt(run_id)
                except Exception as inc_err:
                    logger.warning(
                        "Failed to increment retry attempt: run_id=%s, "
                        "error=%s",
                        run_id,
                        inc_err,
                    )

            # Publish with retry logic
            if _publish_with_retry(
                workflow_id=workflow_id,
                run_id=run_id,
                data=data,
                completed_steps=completed_steps,
                delay_seconds=retry_delay,
                attempt=attempt + 1,
            ):
                return JsonResponse(
                    {
                        "status": "retrying",
                        "workflow_id": workflow_id,
                        "run_id": run_id,
                        "attempt": attempt + 1,
                        "retry_delay": retry_delay,
                    }
                )
            # Fall through to DLQ if all publish attempts failed
            logger.warning("Failed to schedule retry after all attempts")

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
            completed_steps=completed_steps,
        )

        # Persist workflow failure (non-blocking)
        _safe_persist_failure(run_id, str(wf_err))

        return JsonResponse(
            {
                "error": "Workflow execution failed",
                "workflow_id": workflow_id,
                "run_id": run_id,
                "added_to_dlq": True,
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

        # Persist workflow failure (non-blocking)
        _safe_persist_failure(run_id, "Unexpected internal error")

        return JsonResponse(
            {
                "error": "Internal server error",
                "workflow_id": workflow_id,
                "run_id": run_id,
            },
            status=500,
        )

    finally:
        # Always track request end for graceful shutdown
        shutdown_manager.track_request_end(run_id)


def _workflow_webhook_inner(
    request: HttpRequest,
    workflow_id: str,
) -> HttpResponse:
    return _workflow_webhook_impl(request, workflow_id)


workflow_webhook = _apply_rate_limit(
    csrf_exempt(
        require_POST(_workflow_webhook_inner),
    )
)  # type: ignore[assignment]

workflow_webhook_raw = _workflow_webhook_inner
