from __future__ import annotations

import base64
import logging

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error
from django.core.checks import Warning
from django.core.checks import register

logger = logging.getLogger(__name__)


def _is_qstash_token_format_valid(token: str) -> bool:
    return token.startswith("qstash_")


def _is_base64(value: str) -> bool:
    try:
        base64.b64decode(value, validate=True)
    except ValueError:
        return False
    return True


def _is_webhook_path_valid(path: str) -> bool:
    return path.startswith("/") and path.endswith("/")


def _is_domain_secure(domain: str, debug: bool) -> bool:
    if domain.startswith("https://"):
        return True
    if debug and domain.startswith("http://localhost"):
        return True
    if debug and domain.startswith("http://127.0.0.1"):
        return True
    return False


def _check_qstash_connectivity() -> bool:
    token = getattr(settings, "QSTASH_TOKEN", None)
    if not token:
        return False

    try:
        import requests

        response = requests.get(
            "https://qstash.upstash.io/v2/topics",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        response.raise_for_status()
    except Exception:
        return False
    return True


def _migrations_pending() -> bool:
    try:
        from django.db import connections
        from django.db.migrations.executor import MigrationExecutor

        connection = connections["default"]
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        return bool(executor.migration_plan(targets))
    except Exception:
        logger.warning("Failed to check migration status", exc_info=True)
        return False


class DjangoHookflowConfig(AppConfig):
    """Django app configuration for django-hookflow."""

    name = "django_hookflow"
    verbose_name = "Django Hookflow"
    default_auto_field = (  # type: ignore[assignment]
        "django.db.models.BigAutoField"
    )

    def ready(self) -> None:
        """
        Perform startup validation when the app is ready.

        This validates that required settings are configured and logs
        warnings for recommended settings. Also sets up signal handlers
        for graceful shutdown.
        """
        self._validate_configuration()
        self._setup_shutdown_handlers()

    def _validate_configuration(self) -> None:
        """Validate hookflow configuration at startup."""
        debug = getattr(settings, "DEBUG", False)

        # Check for QStash token
        qstash_token = getattr(settings, "QSTASH_TOKEN", None)
        if not qstash_token:
            logger.warning(
                "QSTASH_TOKEN is not configured. Workflow triggers will fail."
            )
        elif not _is_qstash_token_format_valid(qstash_token):
            logger.warning(
                "QSTASH_TOKEN does not start with 'qstash_'. "
                "Confirm the token format."
            )

        # Check for domain configuration
        domain = getattr(settings, "DJANGO_HOOKFLOW_DOMAIN", None)
        if not domain:
            logger.warning(
                "DJANGO_HOOKFLOW_DOMAIN is not configured. "
                "Workflow triggers will fail."
            )
        elif not _is_domain_secure(domain, debug):
            logger.warning(
                "DJANGO_HOOKFLOW_DOMAIN should use https in production."
            )

        # Check signing keys for webhook verification
        current_key = getattr(settings, "QSTASH_CURRENT_SIGNING_KEY", None)
        next_key = getattr(settings, "QSTASH_NEXT_SIGNING_KEY", None)
        if not current_key or not next_key:
            logger.warning(
                "QStash signing keys not configured. "
                "Webhook signature verification will fail."
            )
        else:
            if not _is_base64(current_key):
                logger.warning(
                    "QSTASH_CURRENT_SIGNING_KEY is not valid base64."
                )
            if not _is_base64(next_key):
                logger.warning("QSTASH_NEXT_SIGNING_KEY is not valid base64.")

        # Check webhook path formatting
        webhook_path = getattr(
            settings,
            "DJANGO_HOOKFLOW_WEBHOOK_PATH",
            "/hookflow/",
        )
        if webhook_path and not _is_webhook_path_valid(webhook_path):
            logger.warning(
                "DJANGO_HOOKFLOW_WEBHOOK_PATH should start and end with '/'."
            )

        # Log persistence status
        if getattr(settings, "DJANGO_HOOKFLOW_PERSISTENCE_ENABLED", True):
            logger.info("Workflow persistence is enabled")
        else:
            if debug:
                logger.debug(
                    "Workflow persistence is disabled. Enable with "
                    "DJANGO_HOOKFLOW_PERSISTENCE_ENABLED=True for "
                    "durability features."
                )
            else:
                logger.warning(
                    "Workflow persistence is disabled in non-DEBUG mode. "
                    "Enable DJANGO_HOOKFLOW_PERSISTENCE_ENABLED=True "
                    "for durability features."
                )

        if getattr(settings, "DJANGO_HOOKFLOW_VALIDATE_CONNECTIVITY", False):
            if _check_qstash_connectivity():
                logger.info("QStash connectivity check succeeded")
            else:
                logger.warning("QStash connectivity check failed")

        if _migrations_pending():
            logger.warning("Pending migrations detected for django_hookflow")

    def _setup_shutdown_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        from django_hookflow.shutdown import get_shutdown_manager

        shutdown_manager = get_shutdown_manager()
        shutdown_manager.install_signal_handlers()


@register()
def check_hookflow_settings(app_configs, **kwargs):
    """
    Django system check for hookflow configuration.

    Returns warnings and errors for missing or invalid settings.
    """
    errors = []
    debug = getattr(settings, "DEBUG", False)
    persistence_enabled = getattr(
        settings,
        "DJANGO_HOOKFLOW_PERSISTENCE_ENABLED",
        True,
    )

    # Check QStash token
    qstash_token = getattr(settings, "QSTASH_TOKEN", None)
    if not qstash_token:
        errors.append(
            Warning(
                "QSTASH_TOKEN is not configured",
                hint=(
                    "Set QSTASH_TOKEN in your Django settings to enable "
                    "workflow triggers."
                ),
                id="django_hookflow.W001",
            )
        )
    elif not _is_qstash_token_format_valid(qstash_token):
        errors.append(
            Warning(
                "QSTASH_TOKEN does not start with 'qstash_'",
                hint=(
                    "Confirm the QStash token format from the Upstash console."
                ),
                id="django_hookflow.W004",
            )
        )

    # Check domain
    domain = getattr(settings, "DJANGO_HOOKFLOW_DOMAIN", None)
    if not domain:
        errors.append(
            Warning(
                "DJANGO_HOOKFLOW_DOMAIN is not configured",
                hint=(
                    "Set DJANGO_HOOKFLOW_DOMAIN to your public URL "
                    "(e.g., 'https://myapp.example.com')"
                ),
                id="django_hookflow.W002",
            )
        )
    elif not _is_domain_secure(domain, debug):
        errors.append(
            Error(
                "DJANGO_HOOKFLOW_DOMAIN must use https in non-DEBUG mode",
                hint=(
                    "Use https:// for DJANGO_HOOKFLOW_DOMAIN. "
                    "Localhost over http is allowed when DEBUG=True."
                ),
                id="django_hookflow.E001",
            )
        )

    # Check webhook path
    webhook_path = getattr(
        settings,
        "DJANGO_HOOKFLOW_WEBHOOK_PATH",
        "/hookflow/",
    )
    if webhook_path and not _is_webhook_path_valid(webhook_path):
        errors.append(
            Error(
                "DJANGO_HOOKFLOW_WEBHOOK_PATH must start and end with '/'",
                hint=(
                    "Ensure DJANGO_HOOKFLOW_WEBHOOK_PATH is like '/hookflow/'."
                ),
                id="django_hookflow.E002",
            )
        )

    # Check signing keys
    current_key = getattr(settings, "QSTASH_CURRENT_SIGNING_KEY", None)
    next_key = getattr(settings, "QSTASH_NEXT_SIGNING_KEY", None)
    if not current_key or not next_key:
        errors.append(
            Warning(
                "QStash signing keys are not configured",
                hint=(
                    "Set QSTASH_CURRENT_SIGNING_KEY and "
                    "QSTASH_NEXT_SIGNING_KEY for webhook verification."
                ),
                id="django_hookflow.W003",
            )
        )
    else:
        if not _is_base64(current_key):
            errors.append(
                Error(
                    "QSTASH_CURRENT_SIGNING_KEY is not valid base64",
                    hint="Ensure the signing key is base64 encoded.",
                    id="django_hookflow.E003",
                )
            )
        if not _is_base64(next_key):
            errors.append(
                Error(
                    "QSTASH_NEXT_SIGNING_KEY is not valid base64",
                    hint="Ensure the signing key is base64 encoded.",
                    id="django_hookflow.E004",
                )
            )

    if not persistence_enabled and not debug:
        errors.append(
            Warning(
                "DJANGO_HOOKFLOW_PERSISTENCE_ENABLED is disabled",
                hint=(
                    "Enable persistence for production durability features."
                ),
                id="django_hookflow.W005",
            )
        )

    return errors
