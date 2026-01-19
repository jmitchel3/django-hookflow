from __future__ import annotations

from django.contrib import admin

from .dlq import DeadLetterEntry
from .models import StepExecution
from .models import WorkflowRun


class StepExecutionInline(admin.TabularInline):
    """Inline display of step executions within a workflow run."""

    model = StepExecution
    extra = 0
    readonly_fields = ("step_id", "result", "executed_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(WorkflowRun)
class WorkflowRunAdmin(admin.ModelAdmin):
    """Admin interface for workflow runs."""

    list_display = (
        "run_id",
        "workflow_id",
        "status",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "workflow_id", "created_at")
    search_fields = ("run_id", "workflow_id")
    readonly_fields = (
        "run_id",
        "workflow_id",
        "status",
        "data",
        "result",
        "error_message",
        "created_at",
        "updated_at",
        "completed_at",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    inlines = [StepExecutionInline]

    fieldsets = (
        (None, {"fields": ("run_id", "workflow_id", "status")}),
        ("Data", {"fields": ("data", "result", "error_message")}),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at", "completed_at")},
        ),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(StepExecution)
class StepExecutionAdmin(admin.ModelAdmin):
    """Admin interface for step executions."""

    list_display = ("step_id", "workflow_run", "executed_at")
    list_filter = ("executed_at",)
    search_fields = ("step_id", "workflow_run__run_id")
    readonly_fields = ("workflow_run", "step_id", "result", "executed_at")
    ordering = ("-executed_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(DeadLetterEntry)
class DeadLetterEntryAdmin(admin.ModelAdmin):
    """Admin interface for dead letter queue entries."""

    list_display = (
        "workflow_id",
        "run_id",
        "step_id",
        "attempt_count",
        "is_replayed",
        "created_at",
    )
    list_filter = ("workflow_id", "is_replayed", "created_at")
    search_fields = ("workflow_id", "run_id", "step_id", "error_message")
    readonly_fields = (
        "workflow_id",
        "run_id",
        "step_id",
        "payload",
        "completed_steps",
        "error_message",
        "error_traceback",
        "attempt_count",
        "created_at",
        "replayed_at",
        "is_replayed",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    actions = ["replay_entries"]

    fieldsets = (
        (None, {"fields": ("workflow_id", "run_id", "step_id")}),
        ("Payload", {"fields": ("payload", "completed_steps")}),
        (
            "Error",
            {
                "fields": (
                    "error_message",
                    "error_traceback",
                    "attempt_count",
                ),
                "classes": ("collapse",),
            },
        ),
        ("Replay", {"fields": ("is_replayed", "replayed_at")}),
        ("Timestamps", {"fields": ("created_at",)}),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.action(description="Replay selected entries")
    def replay_entries(self, request, queryset):
        """Replay selected DLQ entries."""
        replayed = 0
        errors = 0
        for entry in queryset.filter(is_replayed=False):
            try:
                entry.replay()
                replayed += 1
            except Exception:
                errors += 1

        if replayed:
            self.message_user(request, f"Replayed {replayed} entries.")
        if errors:
            self.message_user(
                request,
                f"Failed to replay {errors} entries.",
                level="error",
            )
