# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Package Manager

Always use `uv` instead of `pip` or raw `python` commands:
- `uv sync` to install dependencies
- `uv run pytest` to run tests
- `uv add <package>` to add dependencies
- `uv lock` to update the lock file
- `uv build` to build the package

## Commands

```bash
# Run all tests
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/test_workflows.py -v

# Run a specific test
uv run pytest tests/test_workflows.py::test_function_name -v

# Run tests with coverage
uv run pytest tests/ --cov=django_hookflow --cov-report=term-missing

# Type checking
uv run mypy src/django_hookflow

# Linting (pre-commit runs black, isort, flake8)
pre-commit run --all-files

# Build package
uv build
```

## Architecture

Django-hookflow provides **durable, multi-step workflows** for Django using QStash (Upstash) as the orchestration layer.

### Core Flow

1. `@workflow` decorator registers functions and adds a `.trigger()` method
2. `.trigger()` publishes initial payload to QStash
3. QStash calls webhook at `/hookflow/workflow/{workflow_id}/`
4. Webhook executes workflow function with `WorkflowContext`
5. Each `ctx.step.run/sleep/call` checks if step already completed (returns cached result) or executes and raises `StepCompleted` exception
6. `StepCompleted` halts execution and schedules next QStash callback with updated `completed_steps`
7. Workflow re-executes from start on each callback, skipping completed steps via cached results
8. When no more steps raise `StepCompleted`, workflow returns final result

### Key Components

| File | Purpose |
|------|---------|
| `workflows/decorator.py` | `@workflow` decorator, `WorkflowWrapper` class |
| `workflows/context.py` | `WorkflowContext`, `StepManager` (run/sleep/call methods) |
| `workflows/registry.py` | Global workflow registry, `get_workflow()` |
| `workflows/handlers.py` | `verify_qstash_signature()`, `publish_next_step()` |
| `workflows/views.py` | `workflow_webhook()` endpoint |
| `models.py` | `WorkflowRun`, `StepExecution` Django models |
| `persistence.py` | `WorkflowPersistence` CRUD for database storage |
| `dlq.py` | `DeadLetterEntry` for failed workflow recovery |
| `retry.py` | Exponential backoff retry logic |
| `api/views.py` | REST endpoints for workflow status/listing |

### Exception-Based Control Flow

`StepCompleted` exception is the key mechanism - it halts workflow execution after each step, allowing QStash to schedule the next callback. The workflow function re-runs from the beginning each time, but completed steps return cached results immediately.

## Code Style

- Line length: 79 characters (black + isort)
- Type annotations required (mypy strict mode)
- All files must have `from __future__ import annotations` (auto-added by isort)
- Single imports per line (isort force_single_line)
- 100% test coverage required

## Testing

Tests use `pytest-django` with settings from `tests/settings.py` (SQLite in-memory database).
