# Django Hookflow

Durable workflows and GitHub Actions integration for Django, powered by [Upstash QStash](https://upstash.com/docs/qstash) and [Django QStash](https://github.com/jmitchel3/django-qstash)

## Installation

```bash
uv add django-hookflow
```

or

```bash
pip install django-hookflow
```

**Requirements:**
- Python 3.10+
- Django 4.2+

## Features

- **Durable Workflows**: Multi-step workflows that survive restarts and failures
- **GitHub Actions**: Trigger GitHub workflows from Django functions

## Quick Start

### Durable Workflows

Define workflows with steps that automatically checkpoint their progress. If a step fails or the server restarts, the workflow resumes from where it left off.

```python
# app/workflows.py
from django_hookflow import workflow


@workflow
def process_order(ctx):
    order_id = ctx.data.get("order_id")

    # Each step is executed exactly once, even across retries
    validated = ctx.step.run("validate", validate_order, order_id)

    # Durable sleep - doesn't consume server resources
    ctx.step.sleep("wait-for-payment", seconds=60)

    # Make HTTP calls with automatic retry and caching
    payment = ctx.step.call("charge", url="https://api.stripe.com/...", method="POST")

    result = ctx.step.run("fulfill", fulfill_order, order_id, payment)

    return {"status": "completed", "result": result}
```

Trigger workflows programmatically:

```python
# Trigger returns immediately, workflow runs asynchronously
run_id = process_order.trigger(data={"order_id": "12345"})
```

### Configuration

Add to your Django settings:

```python
# Required for workflows
QSTASH_TOKEN = "your-qstash-token"
DJANGO_HOOKFLOW_DOMAIN = "https://your-app.com"
DJANGO_HOOKFLOW_WEBHOOK_PATH = "/hookflow/"  # optional, defaults to /hookflow/

# Required for GitHub Actions
GITHUB_PERSONAL_ACCESS_TOKEN = "your-github-pat"
GITHUB_DEFAULT_REPO = "user/repo"  # optional default
```

Add the webhook URLs to your `urls.py`:

```python
from django.urls import include, path

urlpatterns = [
    path("hookflow/", include("django_hookflow.urls")),
]
```

### GitHub Actions Integration

Trigger GitHub Actions workflows from your Django code:

```python
from django_hookflow import trigger_github_workflow, dispatch_workflow


# As a decorator - triggers workflow after function completes
@trigger_github_workflow(repo="user/repo", workflow_file="deploy.yml")
def deploy_feature(feature_name):
    # Your logic here
    return f"Deploying {feature_name}"


# Direct dispatch
dispatch_workflow(repo="user/repo", workflow_file="build.yml", ref="main")
```

## Workflow Context API

Inside a workflow function, `ctx` provides:

| Property | Description |
|----------|-------------|
| `ctx.data` | Initial payload passed to `.trigger()` |
| `ctx.run_id` | Unique identifier for this workflow run |
| `ctx.workflow_id` | The workflow's identifier |
| `ctx.step` | Step manager for durable operations |

### Step Manager Methods

| Method | Description |
|--------|-------------|
| `ctx.step.run(step_id, fn, *args, **kwargs)` | Execute a function as a durable step |
| `ctx.step.sleep(step_id, seconds)` | Sleep without consuming resources |
| `ctx.step.call(step_id, url, method, body, headers)` | Make a durable HTTP request |

## License

MIT
