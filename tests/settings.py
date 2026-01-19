from __future__ import annotations

SECRET_KEY = "test-secret-key-for-testing-only"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django_qstash",
    "django_hookflow",
]

DATABASES = {}

USE_TZ = True

# GitHub settings for existing tests
GITHUB_PERSONAL_ACCESS_TOKEN = "test-token"
GITHUB_DEFAULT_REPO = "test/repo"

# QStash settings for workflow tests
QSTASH_TOKEN = "test-qstash-token"
QSTASH_CURRENT_SIGNING_KEY = "test-current-signing-key"
QSTASH_NEXT_SIGNING_KEY = "test-next-signing-key"
DJANGO_HOOKFLOW_DOMAIN = "https://example.com"
DJANGO_HOOKFLOW_WEBHOOK_PATH = "/hookflow/"
