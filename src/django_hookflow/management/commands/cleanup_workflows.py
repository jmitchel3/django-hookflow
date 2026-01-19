from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from django_hookflow.dlq import DeadLetterEntry
from django_hookflow.models import WorkflowRun
from django_hookflow.models import WorkflowRunStatus


class Command(BaseCommand):
    """
    Management command to clean up old workflow data.

    This command deletes or archives workflow runs and DLQ entries older
    than the specified number of days. Useful for preventing unbounded
    growth of workflow data.
    """

    help = "Clean up old workflow runs and DLQ entries"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days-old",
            type=int,
            default=30,
            help="Delete workflows older than this many days (default: 30)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )
        parser.add_argument(
            "--include-running",
            action="store_true",
            help="Also delete running workflows (not recommended)",
        )
        parser.add_argument(
            "--workflows-only",
            action="store_true",
            help="Only clean up workflow runs, not DLQ entries",
        )
        parser.add_argument(
            "--dlq-only",
            action="store_true",
            help="Only clean up DLQ entries, not workflow runs",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of records to delete per batch (default: 1000)",
        )

    def handle(self, *args, **options):
        days_old = options["days_old"]
        dry_run = options["dry_run"]
        include_running = options["include_running"]
        workflows_only = options["workflows_only"]
        dlq_only = options["dlq_only"]
        batch_size = options["batch_size"]

        if days_old < 1:
            raise CommandError("--days-old must be at least 1")

        cutoff_date = timezone.now() - timedelta(days=days_old)

        self.stdout.write(
            f"Cleaning up workflow data older than {days_old} days "
            f"(before {cutoff_date.isoformat()})"
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN - no data will be deleted")
            )

        total_workflows_deleted = 0
        total_dlq_deleted = 0

        # Clean up workflow runs
        if not dlq_only:
            total_workflows_deleted = self._cleanup_workflows(
                cutoff_date=cutoff_date,
                dry_run=dry_run,
                include_running=include_running,
                batch_size=batch_size,
            )

        # Clean up DLQ entries
        if not workflows_only:
            total_dlq_deleted = self._cleanup_dlq(
                cutoff_date=cutoff_date,
                dry_run=dry_run,
                batch_size=batch_size,
            )

        # Summary
        self.stdout.write("")
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN complete. Would delete: "
                    f"{total_workflows_deleted} workflow runs, "
                    f"{total_dlq_deleted} DLQ entries"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Cleanup complete. Deleted: "
                    f"{total_workflows_deleted} workflow runs, "
                    f"{total_dlq_deleted} DLQ entries"
                )
            )

    def _cleanup_workflows(
        self,
        cutoff_date,
        dry_run: bool,
        include_running: bool,
        batch_size: int,
    ) -> int:
        """Clean up old workflow runs."""
        self.stdout.write("\nCleaning up workflow runs...")

        # Build base queryset
        queryset = WorkflowRun.objects.filter(created_at__lt=cutoff_date)

        # Exclude running workflows unless explicitly included
        if not include_running:
            queryset = queryset.exclude(status=WorkflowRunStatus.RUNNING)

        # Count records
        total_count = queryset.count()

        if total_count == 0:
            self.stdout.write("  No workflow runs to clean up")
            return 0

        # Show breakdown by status
        status_counts = {}
        for status in WorkflowRunStatus.choices:
            count = queryset.filter(status=status[0]).count()
            if count > 0:
                status_counts[status[1]] = count

        self.stdout.write(f"  Found {total_count} workflow runs to delete:")
        for status, count in status_counts.items():
            self.stdout.write(f"    - {status}: {count}")

        if dry_run:
            return total_count

        # Delete in batches
        deleted = 0
        while True:
            with transaction.atomic():
                # Get batch of IDs to delete
                batch_ids = list(
                    queryset.values_list("id", flat=True)[:batch_size]
                )
                if not batch_ids:
                    break

                # Delete batch (cascades to StepExecutions)
                batch_deleted, _ = WorkflowRun.objects.filter(
                    id__in=batch_ids
                ).delete()
                deleted += batch_deleted

                self.stdout.write(
                    f"  Deleted {deleted}/{total_count} workflow runs",
                    ending="\r",
                )

        self.stdout.write(f"  Deleted {deleted} workflow runs          ")
        return deleted

    def _cleanup_dlq(
        self,
        cutoff_date,
        dry_run: bool,
        batch_size: int,
    ) -> int:
        """Clean up old DLQ entries."""
        self.stdout.write("\nCleaning up DLQ entries...")

        # Get replayed entries older than cutoff
        replayed_queryset = DeadLetterEntry.objects.filter(
            created_at__lt=cutoff_date,
            is_replayed=True,
        )

        # Get all entries much older (double the age) regardless of status
        very_old_cutoff = cutoff_date - timedelta(days=cutoff_date.day)
        very_old_queryset = DeadLetterEntry.objects.filter(
            created_at__lt=very_old_cutoff
        )

        replayed_count = replayed_queryset.count()
        very_old_count = very_old_queryset.exclude(
            id__in=replayed_queryset.values_list("id", flat=True)
        ).count()

        total_count = replayed_count + very_old_count

        if total_count == 0:
            self.stdout.write("  No DLQ entries to clean up")
            return 0

        self.stdout.write(f"  Found {total_count} DLQ entries to delete:")
        self.stdout.write(f"    - Replayed entries: {replayed_count}")
        self.stdout.write(f"    - Very old entries: {very_old_count}")

        if dry_run:
            return total_count

        # Delete replayed entries in batches
        deleted = 0
        while True:
            with transaction.atomic():
                batch_ids = list(
                    replayed_queryset.values_list("id", flat=True)[:batch_size]
                )
                if not batch_ids:
                    break

                batch_deleted, _ = DeadLetterEntry.objects.filter(
                    id__in=batch_ids
                ).delete()
                deleted += batch_deleted

                self.stdout.write(
                    f"  Deleted {deleted}/{total_count} DLQ entries",
                    ending="\r",
                )

        # Delete very old entries in batches
        while True:
            with transaction.atomic():
                batch_ids = list(
                    very_old_queryset.values_list("id", flat=True)[:batch_size]
                )
                if not batch_ids:
                    break

                batch_deleted, _ = DeadLetterEntry.objects.filter(
                    id__in=batch_ids
                ).delete()
                deleted += batch_deleted

                self.stdout.write(
                    f"  Deleted {deleted}/{total_count} DLQ entries",
                    ending="\r",
                )

        self.stdout.write(f"  Deleted {deleted} DLQ entries          ")
        return deleted
