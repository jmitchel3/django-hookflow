# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed
- Removed pre-built REST API (`django_hookflow.api` module) - developers should build their own API endpoints using the provided models and persistence layer
- Removed optional `djangorestframework` dependency

## [0.0.3] - 2024-01-XX

### Added
- Production hardening features:
  - JWT signature verification for webhook security
  - Concurrency-safe step execution with database locking
  - Comprehensive error handling and logging
- `cleanup_workflows` management command for database maintenance
- Django admin interface for viewing workflow runs, steps, and DLQ entries
- Configuration validation at startup with Django system checks

### Changed
- Improved error messages and logging throughout

## [0.0.2] - 2024-01-XX

### Added
- Database persistence for workflow state (`WorkflowRun`, `StepExecution` models)
- Dead Letter Queue (DLQ) for failed workflow recovery
- Exponential backoff retry logic
- `WorkflowPersistence` class for state management
- Status tracking (pending, running, completed, failed)

### Changed
- Workflows now persist state to database when `DJANGO_HOOKFLOW_PERSISTENCE_ENABLED=True`

## [0.0.1] - 2024-01-XX

### Added
- Initial release
- `@workflow` decorator for defining durable workflows
- `WorkflowContext` with `ctx.step.run()`, `ctx.step.sleep()`, `ctx.step.call()` methods
- QStash integration for workflow orchestration
- Webhook endpoints for receiving QStash callbacks
- Basic README documentation

[Unreleased]: https://github.com/jmitchel3/django-hookflow/compare/v0.0.3...HEAD
[0.0.3]: https://github.com/jmitchel3/django-hookflow/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/jmitchel3/django-hookflow/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/jmitchel3/django-hookflow/releases/tag/v0.0.1
