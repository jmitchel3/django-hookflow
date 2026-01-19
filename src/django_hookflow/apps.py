from __future__ import annotations

import logging

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Warning
from django.core.checks import register

logger = logging.getLogger(__name__)


class DjangoHookflowConfig(AppConfig):
    """Django app configuration for django-hookflow."""

    name = "django_hookflow"
    verbose_name = "Django Hookflow"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        """
        Perform startup validation when the app is ready.

        This validates that required settings are configured and logs
        warnings for recommended settings.
        """
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        """Validate hookflow configuration at startup."""
        # Check for QStash token
        qstash_token = getattr(settings, "QSTASH_TOKEN", None)
        if not qstash_token:
            logger.warning(
                "QSTASH_TOKEN is not configured. Workflow triggers will fail."
            )

        # Check for domain configuration
        domain = getattr(settings, "DJANGO_HOOKFLOW_DOMAIN", None)
        if not domain:
            logger.warning(
                "DJANGO_HOOKFLOW_DOMAIN is not configured. "
                "Workflow triggers will fail."
            )

        # Check signing keys for webhook verification
        current_key = getattr(settings, "QSTASH_CURRENT_SIGNING_KEY", None)
        next_key = getattr(settings, "QSTASH_NEXT_SIGNING_KEY", None)
        if not current_key or not next_key:
            logger.warning(
                "QStash signing keys not configured. "
                "Webhook signature verification will fail."
            )

        # Log persistence status
        if getattr(settings, "DJANGO_HOOKFLOW_PERSISTENCE_ENABLED", False):
            logger.info("Workflow persistence is enabled")
        else:
            logger.debug(
                "Workflow persistence is disabled. Enable with "
                "DJANGO_HOOKFLOW_PERSISTENCE_ENABLED=True for "
                "durability features."
            )


@register()
def check_hookflow_settings(app_configs, **kwargs):
    """
    Django system check for hookflow configuration.

    Returns warnings for missing recommended settings.
    """
    errors = []

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

    return errors
