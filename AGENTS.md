# AGENTS.md

This file orients coding agents working in this repo.
Keep changes aligned with existing patterns and tool choices.

## Essentials

- Repo: django-hookflow (durable workflows for Django using QStash and Upstash Workflows).
- Package manager: use `uv` for all Python actions.
- Python: >=3.10.
- Formatting: Black + isort with 79-char lines.
- Typing: mypy strict, type annotations required.
- Tests: pytest-django with `tests/settings.py`.

## Setup

- Install dependencies: `uv sync`
- Add dependency: `uv add <package>`
- Update lockfile: `uv lock`
- Build package: `uv build`

## Test Commands

- Run all tests: `uv run pytest tests/ -v`
- Single test file: `uv run pytest tests/test_workflows.py -v`
- Single test: `uv run pytest tests/test_workflows.py::test_function_name -v`
- Coverage: `uv run pytest tests/ --cov=django_hookflow --cov-report=term-missing`

## Lint / Type Check

- Type check: `uv run mypy src/django_hookflow`
- Lint/format via pre-commit: `pre-commit run --all-files`
- Formatting is driven by Black and isort (configured in `pyproject.toml`).

## Code Style Guidelines

### Imports

- Always include `from __future__ import annotations` at top of files.
- isort is configured with `force_single_line = true`.
- One import per line, grouped: stdlib, third-party, local.
- Prefer explicit imports over wildcard imports.

### Formatting

- Line length: 79 characters.
- Use Black formatting; do not hand-align with extra spaces.
- Use trailing commas for multi-line literals and call arguments.
- Keep blank lines between logical sections (imports, constants, classes).

### Typing

- Type annotations are required (mypy strict).
- Use `dict[str, Any]` and `list[str]` style annotations (PEP 585).
- Use `| None` instead of `Optional` (PEP 604).
- Keep return types explicit, especially for public APIs.
- Use `TypeVar` and `Callable` when needed for generics.

### Naming

- Classes: `CapWords` (e.g., `WorkflowContext`).
- Functions/methods: `snake_case`.
- Constants: `UPPER_SNAKE_CASE`.
- Private helpers: prefix with `_` and keep module-private when possible.

### Django Conventions

- Models live in `src/django_hookflow/models.py` and `dlq.py`.
- Use `models.TextChoices` for enumerations.
- Prefer `models.JSONField` for structured payloads.
- Keep model `__str__` methods simple and deterministic.

### Error Handling

- Wrap external failures in `WorkflowError` for workflow execution.
- Use `StepCompleted` to short-circuit durable steps.
- Log and continue for non-critical persistence failures.
- Avoid broad `except Exception` unless immediately logging and re-raising
  or returning a well-defined error response.

### Logging

- Use module-level `logger = logging.getLogger(__name__)`.
- Prefer structured logging with placeholders, not f-strings.
- Log failures at `warning` or `exception` depending on severity.

### APIs and Side Effects

- Use `getattr(settings, ...)` for optional settings.
- Ensure QStash calls include deduplication when needed.
- Avoid side effects in import time; use lazy imports for persistence.

### Tests

- Tests use `pytest` + `pytest-django` with `tests/settings.py`.
- Use `RequestFactory` or mocks for Django requests.
- When testing workflow steps, expect `StepCompleted` exceptions.
- Coverage target is 100%; keep tests thorough.

## Architecture Pointers

- Workflow decorator: `src/django_hookflow/workflows/decorator.py`.
- Workflow context/steps: `src/django_hookflow/workflows/context.py`.
- Webhook handler: `src/django_hookflow/workflows/views.py`.
- QStash client/receiver: `src/django_hookflow/qstash/`.
- Persistence: `src/django_hookflow/persistence.py`.

## Repo-Specific Rules

- Always use `uv` commands (no pip or raw python invocations).
- Keep line length to 79 and preserve `__future__` imports.
- Single import per line (`isort` force_single_line).
- Maintain strict typing and full coverage.

## Notes on Agent Files

- No Cursor rules or Copilot instructions were found in this repo.
- If new rules are added under `.cursor/rules/` or
  `.github/copilot-instructions.md`, update this document.
