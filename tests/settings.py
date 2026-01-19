from __future__ import annotations

SECRET_KEY = "test-secret-key-for-testing-only"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django_hookflow",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

USE_TZ = True

# QStash settings for workflow tests
QSTASH_TOKEN = "qstash_test_token"
QSTASH_CURRENT_SIGNING_KEY = "c2lnbmVkLWtleS0x"
QSTASH_NEXT_SIGNING_KEY = "c2lnbmVkLWtleS0y"

# django-hookflow settings
DJANGO_HOOKFLOW_DOMAIN = "https://example.com"
DJANGO_HOOKFLOW_WEBHOOK_PATH = "/hookflow/"
DJANGO_HOOKFLOW_PERSISTENCE_ENABLED = False
