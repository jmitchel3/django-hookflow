from __future__ import annotations

from django.urls import path

from .views import workflow_webhook

app_name = "django_hookflow_workflows"

urlpatterns = [
    path(
        "workflow/<str:workflow_id>/",
        workflow_webhook,
        name="workflow_webhook",
    ),
]
