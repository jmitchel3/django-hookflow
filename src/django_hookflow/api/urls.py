from __future__ import annotations

from django.urls import path

from .views import workflow_list
from .views import workflow_status
from .views import workflow_types

app_name = "django_hookflow_api"

urlpatterns = [
    path("workflows/", workflow_list, name="workflow_list"),
    path("workflows/types/", workflow_types, name="workflow_types"),
    path("workflows/<str:run_id>/", workflow_status, name="workflow_status"),
]
