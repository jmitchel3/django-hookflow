from __future__ import annotations

from django.urls import include
from django.urls import path

app_name = "django_hookflow"

urlpatterns = [
    path("", include("django_hookflow.workflows.urls")),
]
