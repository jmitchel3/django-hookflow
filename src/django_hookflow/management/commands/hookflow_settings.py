from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

_SETTINGS = [
    {
        "name": "QSTASH_TOKEN",
        "required": True,
        "default": None,
        "env": "QSTASH_TOKEN",
        "secret": True,
    },
    {
        "name": "QSTASH_CURRENT_SIGNING_KEY",
        "required": True,
        "default": None,
        "env": "QSTASH_CURRENT_SIGNING_KEY",
        "secret": True,
    },
    {
        "name": "QSTASH_NEXT_SIGNING_KEY",
        "required": True,
        "default": None,
        "env": "QSTASH_NEXT_SIGNING_KEY",
        "secret": True,
    },
    {
        "name": "DJANGO_HOOKFLOW_DOMAIN",
        "required": True,
        "default": None,
        "env": "DJANGO_HOOKFLOW_DOMAIN",
        "secret": False,
    },
    {
        "name": "DJANGO_HOOKFLOW_WEBHOOK_PATH",
        "required": False,
        "default": "/hookflow/",
        "env": "DJANGO_HOOKFLOW_WEBHOOK_PATH",
        "secret": False,
    },
    {
        "name": "DJANGO_HOOKFLOW_PERSISTENCE_ENABLED",
        "required": False,
        "default": True,
        "env": "DJANGO_HOOKFLOW_PERSISTENCE_ENABLED",
        "secret": False,
    },
    {
        "name": "DJANGO_HOOKFLOW_VALIDATE_CONNECTIVITY",
        "required": False,
        "default": False,
        "env": "DJANGO_HOOKFLOW_VALIDATE_CONNECTIVITY",
        "secret": False,
    },
]


def _format_value(value: Any, secret: bool) -> str:
    if value is None:
        return "unset"

    text = str(value)
    if not secret:
        return text

    if len(text) <= 8:
        return "*" * len(text)

    return f"{text[:4]}...{text[-4:]}"


class Command(BaseCommand):
    help = "List django-hookflow settings and current values"

    def handle(self, *args, **options) -> None:
        self.stdout.write("Django Hookflow settings")
        self.stdout.write("")

        sentinel = object()

        for item in _SETTINGS:
            name = item["name"]
            required = "required" if item["required"] else "optional"
            default = item["default"]
            default_text = "-" if default is None else str(default)
            current = getattr(settings, name, sentinel)
            current_text = "unset"
            if current is not sentinel:
                current_text = _format_value(current, item["secret"])

            self.stdout.write(name)
            self.stdout.write(f"  Required: {required}")
            self.stdout.write(f"  Default: {default_text}")
            self.stdout.write(f"  Current: {current_text}")
            self.stdout.write(f"  Env: {item['env']}")
            self.stdout.write("")
