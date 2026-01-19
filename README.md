# Django Hookflow

Durable workflows for Django, powered by [Upstash QStash](https://upstash.com/docs/qstash).

Build multi-step workflows that survive server restarts, network failures, and deployment updates. Each step is executed exactly once, and the workflow automatically resumes from where it left off.

## Installation

```bash
pip install django-hookflow
```

Optional extras:

```bash
pip install "django-hookflow[ratelimit]"
pip install "django-hookflow[all]"
```

or with uv:

```bash
uv add django-hookflow
```

Optional extras:

```bash
uv add "django-hookflow[ratelimit]"
uv add "django-hookflow[all]"
```

**Requirements:**
- Python 3.10+
- Django 4.2+

## Quick Start

### 1. Configure Settings

Add to your Django settings:

```python
# settings.py

INSTALLED_APPS = [
    # ...
    "django_hookflow",
]

# Required: QStash credentials (get these from https://console.upstash.com/qstash)
QSTASH_TOKEN = "your-qstash-token"
QSTASH_CURRENT_SIGNING_KEY = "your-current-signing-key"
QSTASH_NEXT_SIGNING_KEY = "your-next-signing-key"

# Required: Your public domain where QStash can reach your webhooks
DJANGO_HOOKFLOW_DOMAIN = "https://your-app.com"

# Optional: Custom webhook path (default: /hookflow/)
DJANGO_HOOKFLOW_WEBHOOK_PATH = "/hookflow/"

# Optional: Enable or disable database persistence (enabled by default)
DJANGO_HOOKFLOW_PERSISTENCE_ENABLED = True
```

### 2. Add URL Routes

```python
# urls.py
from django.urls import include, path

urlpatterns = [
    path("hookflow/", include("django_hookflow.urls")),
]
```

### 3. Run Migrations (if using persistence)

```bash
python manage.py migrate django_hookflow
```

### 4. Define a Workflow

```python
# myapp/workflows.py
from django_hookflow import workflow


@workflow
def process_order(ctx):
    """Process an order with multiple durable steps."""
    order_id = ctx.data.get("order_id")

    # Step 1: Validate the order (executed exactly once)
    validated = ctx.step.run("validate", validate_order, order_id)

    # Step 2: Wait for payment confirmation (durable sleep)
    ctx.step.sleep("wait-for-payment", seconds=60)

    # Step 3: Charge the payment (durable HTTP call)
    payment = ctx.step.call(
        "charge",
        url="https://api.stripe.com/v1/charges",
        method="POST",
        body={"amount": validated["total"], "order_id": order_id},
        headers={"Authorization": "Bearer sk_..."},
    )

    # Step 4: Fulfill the order
    result = ctx.step.run("fulfill", fulfill_order, order_id, payment)

    return {"status": "completed", "result": result}


def validate_order(order_id):
    """Validate order exists and has items."""
    # Your validation logic here
    return {"order_id": order_id, "total": 9999}


def fulfill_order(order_id, payment):
    """Ship the order."""
    # Your fulfillment logic here
    return {"shipped": True}
```

### 5. Trigger the Workflow

```python
# Trigger returns immediately, workflow runs asynchronously
run_id = process_order.trigger(data={"order_id": "12345"})
print(f"Started workflow with run_id: {run_id}")
```

## How It Works

1. **Trigger**: When you call `.trigger()`, a message is published to QStash with your workflow payload
2. **Webhook**: QStash calls your webhook endpoint at `/hookflow/workflow/{workflow_id}/`
3. **Execute**: The webhook executes your workflow function with a `WorkflowContext`
4. **Checkpoint**: Each `ctx.step.*` call checks if the step already completed (returns cached result) or executes and raises `StepCompleted`
5. **Schedule Next**: `StepCompleted` halts execution and schedules the next QStash callback with updated state
6. **Resume**: The workflow re-executes from the start on each callback, skipping completed steps via cached results
7. **Complete**: When all steps finish without raising `StepCompleted`, the workflow returns its final result

## Configuration Reference

### Required Settings

| Setting | Description | Example |
|---------|-------------|---------|
| `QSTASH_TOKEN` | Your QStash API token | `"eyJ..."` |
| `QSTASH_CURRENT_SIGNING_KEY` | Current webhook signing key | `"sig_..."` |
| `QSTASH_NEXT_SIGNING_KEY` | Next webhook signing key (for key rotation) | `"sig_..."` |
| `DJANGO_HOOKFLOW_DOMAIN` | Public URL where QStash can reach your app | `"https://myapp.com"` |

### Optional Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `DJANGO_HOOKFLOW_WEBHOOK_PATH` | `"/hookflow/"` | Base path for webhook endpoints |
| `DJANGO_HOOKFLOW_PERSISTENCE_ENABLED` | `True` | Enable database persistence |
| `DJANGO_HOOKFLOW_VERIFY_SSL` | `True` | Verify SSL certificates for HTTP steps |
| `DJANGO_HOOKFLOW_RATE_LIMIT` | `"100/minute"` | Rate limit for webhook requests |
| `DJANGO_HOOKFLOW_MAX_PAYLOAD_SIZE` | `1048576` | Max payload size in bytes |
| `DJANGO_HOOKFLOW_VALIDATE_CONNECTIVITY` | `False` | Check QStash connectivity on startup |

### Environment Variables Example

```bash
# .env
QSTASH_TOKEN=eyJVc2VySUQiOiIxMjM0NTY3ODkwIiwiQXBpS2V5IjoiYWJjZGVmIn0=
QSTASH_CURRENT_SIGNING_KEY=sig_abc123...
QSTASH_NEXT_SIGNING_KEY=sig_def456...
DJANGO_HOOKFLOW_DOMAIN=https://myapp.example.com
DJANGO_HOOKFLOW_PERSISTENCE_ENABLED=true
```

```python
# settings.py
import os

QSTASH_TOKEN = os.environ.get("QSTASH_TOKEN")
QSTASH_CURRENT_SIGNING_KEY = os.environ.get("QSTASH_CURRENT_SIGNING_KEY")
QSTASH_NEXT_SIGNING_KEY = os.environ.get("QSTASH_NEXT_SIGNING_KEY")
DJANGO_HOOKFLOW_DOMAIN = os.environ.get("DJANGO_HOOKFLOW_DOMAIN")
DJANGO_HOOKFLOW_PERSISTENCE_ENABLED = (
    os.environ.get("DJANGO_HOOKFLOW_PERSISTENCE_ENABLED", "").lower() == "true"
)
```

## Workflow Context API

Inside a workflow function, `ctx` provides:

| Property | Type | Description |
|----------|------|-------------|
| `ctx.data` | `dict` | Initial payload passed to `.trigger()` |
| `ctx.run_id` | `str` | Unique identifier for this workflow run |
| `ctx.workflow_id` | `str` | The workflow's identifier |
| `ctx.step` | `StepManager` | Step manager for durable operations |

### Step Manager Methods

#### `ctx.step.run(step_id, fn, *args, **kwargs)`

Execute a function as a durable step. The function is called with the provided arguments, and its result is cached. On retry, the cached result is returned without re-executing.

```python
result = ctx.step.run("my-step", my_function, arg1, arg2, kwarg1="value")
```

#### `ctx.step.sleep(step_id, seconds)`

Sleep without consuming server resources. The workflow yields to QStash, which schedules the next callback after the delay.

```python
ctx.step.sleep("wait", seconds=300)  # Wait 5 minutes
```

#### `ctx.step.call(step_id, url, method="GET", body=None, headers=None)`

Make a durable HTTP request. The response is cached, so retries don't re-execute the request.

```python
response = ctx.step.call(
    "api-call",
    url="https://api.example.com/endpoint",
    method="POST",
    body={"key": "value"},
    headers={"Authorization": "Bearer token"},
)
# response = {"status_code": 200, "data": {...}}
```

## Workflow Patterns

### Sequential Steps

```python
@workflow
def sequential_workflow(ctx):
    step1_result = ctx.step.run("step-1", do_step_1)
    step2_result = ctx.step.run("step-2", do_step_2, step1_result)
    step3_result = ctx.step.run("step-3", do_step_3, step2_result)
    return step3_result
```

### Conditional Logic

```python
@workflow
def conditional_workflow(ctx):
    data = ctx.step.run("fetch-data", fetch_data)

    if data.get("needs_approval"):
        ctx.step.run("request-approval", send_approval_request, data)
        ctx.step.sleep("wait-for-approval", seconds=3600)  # Wait 1 hour
        approved = ctx.step.run("check-approval", check_approval_status, data["id"])
        if not approved:
            return {"status": "rejected"}

    result = ctx.step.run("process", process_data, data)
    return {"status": "completed", "result": result}
```

### External API Integration

```python
@workflow
def api_integration_workflow(ctx):
    # Create resource in external system
    created = ctx.step.call(
        "create-resource",
        url="https://api.external.com/resources",
        method="POST",
        body=ctx.data,
        headers={"Authorization": f"Bearer {settings.API_KEY}"},
    )

    resource_id = created["data"]["id"]

    # Poll for completion
    ctx.step.sleep("wait-for-processing", seconds=30)

    status = ctx.step.call(
        "check-status",
        url=f"https://api.external.com/resources/{resource_id}",
        method="GET",
        headers={"Authorization": f"Bearer {settings.API_KEY}"},
    )

    return {"resource_id": resource_id, "status": status["data"]["status"]}
```

### Custom Workflow ID

```python
@workflow(workflow_id="order-processor-v2")
def process_order(ctx):
    pass  # Your workflow logic
```

### Custom Run ID

```python
# Use a deterministic run ID for idempotency
run_id = process_order.trigger(
    data={"order_id": "12345"},
    run_id=f"order-12345-{timestamp}",
)
```

## Database Persistence

When `DJANGO_HOOKFLOW_PERSISTENCE_ENABLED=True`, workflow state is persisted to the database. This enables:

- **Recovery**: Workflows can recover from QStash message failures
- **Monitoring**: View workflow status via Django Admin
- **Debugging**: Inspect step results and error messages

### Models

#### `WorkflowRun`

Tracks workflow executions.

| Field | Description |
|-------|-------------|
| `run_id` | Unique identifier for this run |
| `workflow_id` | The workflow definition ID |
| `status` | `pending`, `running`, `completed`, or `failed` |
| `data` | Initial payload |
| `result` | Final result (if completed) |
| `error_message` | Error message (if failed) |
| `created_at` | When the run started |
| `completed_at` | When the run finished |

#### `StepExecution`

Records individual step results.

| Field | Description |
|-------|-------------|
| `workflow_run` | Foreign key to WorkflowRun |
| `step_id` | Step identifier |
| `result` | Step result (JSON) |
| `executed_at` | When the step executed |

#### `DeadLetterEntry`

Failed workflow entries for manual recovery.

| Field | Description |
|-------|-------------|
| `workflow_id` | The workflow definition ID |
| `run_id` | The failed run ID |
| `payload` | Full workflow payload at failure |
| `error_message` | Error description |
| `is_replayed` | Whether this entry has been replayed |

### Django Admin

Django Hookflow includes admin interfaces for all models. Access them at `/admin/django_hookflow/`.

Features:
- View workflow runs with status filtering
- Inspect step execution results
- Replay failed workflows from the DLQ

## Building Your Own API

Django Hookflow doesn't include pre-built REST endpoints. Instead, use the provided models to build your own API that fits your application's needs.

### Example: Django REST Framework Views

```python
# myapp/api/views.py
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from django_hookflow.models import WorkflowRun, StepExecution


@api_view(["GET"])
def workflow_run_detail(request, run_id):
    """Get details of a specific workflow run."""
    try:
        run = WorkflowRun.objects.prefetch_related("step_executions").get(run_id=run_id)
    except WorkflowRun.DoesNotExist:
        return Response(
            {"error": "Workflow run not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    steps = [
        {
            "step_id": step.step_id,
            "result": step.result,
            "executed_at": step.executed_at.isoformat(),
        }
        for step in run.step_executions.all().order_by("executed_at")
    ]

    return Response(
        {
            "run_id": run.run_id,
            "workflow_id": run.workflow_id,
            "status": run.status,
            "data": run.data,
            "result": run.result,
            "error_message": run.error_message or None,
            "created_at": run.created_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "steps": steps,
        }
    )


@api_view(["GET"])
def workflow_run_list(request):
    """List workflow runs with optional filtering."""
    queryset = WorkflowRun.objects.all()

    # Filter by workflow_id
    workflow_id = request.query_params.get("workflow_id")
    if workflow_id:
        queryset = queryset.filter(workflow_id=workflow_id)

    # Filter by status
    status_filter = request.query_params.get("status")
    if status_filter:
        queryset = queryset.filter(status=status_filter)

    # Pagination
    limit = int(request.query_params.get("limit", 50))
    offset = int(request.query_params.get("offset", 0))

    total = queryset.count()
    runs = queryset.order_by("-created_at")[offset : offset + limit]

    return Response(
        {
            "total": total,
            "runs": [
                {
                    "run_id": run.run_id,
                    "workflow_id": run.workflow_id,
                    "status": run.status,
                    "created_at": run.created_at.isoformat(),
                    "completed_at": run.completed_at.isoformat()
                    if run.completed_at
                    else None,
                }
                for run in runs
            ],
        }
    )
```

### Example: URLs

```python
# myapp/api/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("workflows/", views.workflow_run_list, name="workflow-list"),
    path("workflows/<str:run_id>/", views.workflow_run_detail, name="workflow-detail"),
]
```

### Example: Plain Django Views

```python
# myapp/views.py
import json
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from django_hookflow.models import WorkflowRun


@require_GET
def workflow_status(request, run_id):
    """Simple status endpoint."""
    try:
        run = WorkflowRun.objects.get(run_id=run_id)
    except WorkflowRun.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)

    return JsonResponse(
        {
            "run_id": run.run_id,
            "status": run.status,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
    )
```

## Maintenance

### Cleanup Command

Clean up old workflow data to prevent unbounded database growth:

```bash
# Delete completed/failed workflows older than 30 days
python manage.py cleanup_workflows

# Custom age threshold
python manage.py cleanup_workflows --days-old 7

# Dry run (show what would be deleted)
python manage.py cleanup_workflows --dry-run

# Only clean up DLQ entries
python manage.py cleanup_workflows --dlq-only

# Only clean up workflow runs
python manage.py cleanup_workflows --workflows-only
```

### Recommended: Scheduled Cleanup

Add to your cron or scheduled tasks:

```bash
# Daily cleanup of workflows older than 30 days
0 2 * * * cd /path/to/app && python manage.py cleanup_workflows --days-old 30
```

## Error Handling

### Workflow Errors

Errors in step functions are wrapped in `WorkflowError`:

```python
from django_hookflow.exceptions import WorkflowError


@workflow
def my_workflow(ctx):
    try:
        result = ctx.step.run("risky-step", risky_function)
    except WorkflowError as e:
        # Log the error, the workflow will be marked as failed
        raise
```

### Retry Behavior

By default, QStash retries failed deliveries. Django Hookflow includes logic to determine if errors are retryable:

- **Retryable**: Network errors, timeouts, 5xx responses
- **Non-retryable**: `ValueError`, `TypeError`, `KeyError`, "not found" errors

Failed workflows that exhaust retries are added to the Dead Letter Queue for manual review.

### QStash Built-in Reliability

QStash (Upstash's message queue) provides several built-in reliability features that django-hookflow leverages:

- **Automatic Retries**: QStash automatically retries webhook delivery with exponential backoff (up to 5 retries by default)
- **At-Least-Once Delivery**: Messages are guaranteed to be delivered at least once
- **Deduplication**: Use `deduplication_id` to prevent duplicate processing within a time window
- **Dead Letter Queue**: Failed messages are automatically moved to QStash's DLQ for inspection
- **High Availability**: QStash is a managed service with built-in redundancy

Because QStash handles retry and failure detection at the infrastructure level, django-hookflow doesn't implement client-side patterns like circuit breakers. If QStash is temporarily unreachable, the publish call will fail immediately, and you can handle it in your application code (e.g., queue locally for retry, return an error to the user, etc.).

For more details, see the [QStash documentation](https://upstash.com/docs/qstash/features/retry).

### Dead Letter Queue

View and replay failed workflows via Django Admin or programmatically:

```python
from django_hookflow.dlq import DeadLetterEntry

# Get unreplayed failures
failures = DeadLetterEntry.objects.filter(is_replayed=False)

for entry in failures:
    print(f"Failed: {entry.workflow_id} - {entry.error_message}")

    # Replay the workflow
    new_run_id = entry.replay()
    print(f"Replayed as: {new_run_id}")
```

## Troubleshooting

### "QSTASH_TOKEN is not configured"

Ensure you've set the `QSTASH_TOKEN` in your Django settings. Get your token from the [Upstash Console](https://console.upstash.com/qstash).

### "DJANGO_HOOKFLOW_DOMAIN is not configured"

Set `DJANGO_HOOKFLOW_DOMAIN` to your public URL. For local development, use a tunnel like ngrok:

```bash
ngrok http 8000
# Use the ngrok URL as DJANGO_HOOKFLOW_DOMAIN
```

### Webhooks not being received

1. Verify your domain is publicly accessible
2. Check that the webhook path matches your URL configuration
3. Verify QStash signing keys are correct
4. Check Django logs for signature verification errors

### Workflow stuck in "running" status

This can happen if:
1. QStash message delivery failed
2. Your server crashed during execution
3. A step raised an unexpected exception

Solutions:
- Check the Dead Letter Queue for failures
- Manually trigger a new run with the same data
- If persistence is enabled, the workflow can self-recover on the next callback

### Steps executing multiple times

Ensure:
1. Each step has a unique `step_id` within the workflow
2. Persistence is enabled (`DJANGO_HOOKFLOW_PERSISTENCE_ENABLED=True`)
3. You're using the same `run_id` for retries

## Security

### Webhook Verification

All incoming webhooks are verified using QStash's JWT signatures. Ensure you've configured:
- `QSTASH_CURRENT_SIGNING_KEY`
- `QSTASH_NEXT_SIGNING_KEY`

### Network Security

- Use HTTPS for your `DJANGO_HOOKFLOW_DOMAIN`
- Consider IP allowlisting for QStash IPs
- Don't expose sensitive data in workflow payloads (use references/IDs instead)

## License

MIT
