from __future__ import annotations

SECRET_KEY = "test-secret-key-for-testing-only"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django_qstash",
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
QSTASH_TOKEN = "test-qstash-token"
QSTASH_CURRENT_SIGNING_KEY = "test-current-signing-key"
QSTASH_NEXT_SIGNING_KEY = "test-next-signing-key"
DJANGO_HOOKFLOW_DOMAIN = "https://example.com"
DJANGO_HOOKFLOW_WEBHOOK_PATH = "/hookflow/"

# API authentication settings for tests
HOOKFLOW_API_AUTH_REQUIRED = False  # Disable for tests
HOOKFLOW_API_KEY = "test-api-key"
HOOKFLOW_RATE_LIMIT = None  # Disable rate limiting for tests
