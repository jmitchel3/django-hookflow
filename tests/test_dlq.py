from __future__ import annotations

import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from django_hookflow.dlq import DeadLetterEntry
from django_hookflow.exceptions import WorkflowError


class TestDeadLetterEntryModel(TestCase):
    def test_add_entry_creates_record(self):
        entry = DeadLetterEntry.add_entry(
            workflow_id="test-workflow",
            run_id="test-run-123",
            payload={"data": {"key": "value"}, "completed_steps": {}},
            error_message="Something went wrong",
            step_id="step-1",
            error_traceback="Traceback (most recent call last):\n...",
            attempt_count=3,
        )

        self.assertIsNotNone(entry.id)
        self.assertEqual(entry.workflow_id, "test-workflow")
        self.assertEqual(entry.run_id, "test-run-123")
        self.assertEqual(entry.step_id, "step-1")
        self.assertEqual(
            entry.payload, {"data": {"key": "value"}, "completed_steps": {}}
        )
        self.assertEqual(entry.error_message, "Something went wrong")
        self.assertEqual(
            entry.error_traceback, "Traceback (most recent call last):\n..."
        )
        self.assertEqual(entry.attempt_count, 3)
        self.assertFalse(entry.is_replayed)
        self.assertIsNone(entry.replayed_at)
        self.assertIsNotNone(entry.created_at)

    def test_add_entry_with_minimal_params(self):
        entry = DeadLetterEntry.add_entry(
            workflow_id="test-workflow",
            run_id="test-run-456",
            payload={"data": {}},
            error_message="Error occurred",
        )

        self.assertIsNotNone(entry.id)
        self.assertEqual(entry.workflow_id, "test-workflow")
        self.assertEqual(entry.run_id, "test-run-456")
        self.assertEqual(entry.step_id, "")
        self.assertEqual(entry.error_traceback, "")
        self.assertEqual(entry.attempt_count, 1)

    def test_str_representation(self):
        entry = DeadLetterEntry.add_entry(
            workflow_id="my-workflow",
            run_id="run-789",
            payload={},
            error_message="Test error",
        )

        self.assertEqual(str(entry), "DLQ: my-workflow / run-789")

    def test_entries_ordered_by_created_at_descending(self):
        entry1 = DeadLetterEntry.add_entry(
            workflow_id="workflow-1",
            run_id="run-1",
            payload={},
            error_message="Error 1",
        )
        entry2 = DeadLetterEntry.add_entry(
            workflow_id="workflow-2",
            run_id="run-2",
            payload={},
            error_message="Error 2",
        )

        entries = list(DeadLetterEntry.objects.all())
        # Most recent first
        self.assertEqual(entries[0].id, entry2.id)
        self.assertEqual(entries[1].id, entry1.id)


class TestDeadLetterEntryReplay(TestCase):
    @patch("django_hookflow.workflows.registry.get_workflow")
    def test_replay_triggers_new_workflow(self, mock_get_workflow):
        mock_workflow = MagicMock()
        mock_get_workflow.return_value = mock_workflow

        entry = DeadLetterEntry.add_entry(
            workflow_id="test-workflow",
            run_id="original-run",
            payload={
                "data": {"user_id": 123},
                "completed_steps": {"step-1": "done"},
            },
            error_message="Original error",
        )

        new_run_id = entry.replay()

        # Verify workflow was triggered with original data
        mock_workflow.trigger.assert_called_once()
        call_kwargs = mock_workflow.trigger.call_args.kwargs
        self.assertEqual(call_kwargs["data"], {"user_id": 123})
        self.assertTrue(call_kwargs["run_id"].startswith("replay-"))

        # Verify returned run_id matches
        self.assertEqual(new_run_id, call_kwargs["run_id"])

    @patch("django_hookflow.workflows.registry.get_workflow")
    def test_replay_marks_entry_as_replayed(self, mock_get_workflow):
        mock_workflow = MagicMock()
        mock_get_workflow.return_value = mock_workflow

        entry = DeadLetterEntry.add_entry(
            workflow_id="test-workflow",
            run_id="original-run",
            payload={"data": {}},
            error_message="Original error",
        )

        self.assertFalse(entry.is_replayed)
        self.assertIsNone(entry.replayed_at)

        entry.replay()

        # Refresh from database
        entry.refresh_from_db()

        self.assertTrue(entry.is_replayed)
        self.assertIsNotNone(entry.replayed_at)

    @patch("django_hookflow.workflows.registry.get_workflow")
    def test_replay_raises_error_for_unknown_workflow(self, mock_get_workflow):
        mock_get_workflow.return_value = None

        entry = DeadLetterEntry.add_entry(
            workflow_id="unknown-workflow",
            run_id="test-run",
            payload={"data": {}},
            error_message="Error",
        )

        with self.assertRaises(WorkflowError) as context:
            entry.replay()

        self.assertIn("unknown-workflow", str(context.exception))
        self.assertIn("not found", str(context.exception))

    @patch("django_hookflow.workflows.registry.get_workflow")
    def test_replay_generates_unique_run_id(self, mock_get_workflow):
        mock_workflow = MagicMock()
        mock_get_workflow.return_value = mock_workflow

        entry = DeadLetterEntry.add_entry(
            workflow_id="test-workflow",
            run_id="original-run",
            payload={"data": {}},
            error_message="Error",
        )

        run_id_1 = entry.replay()

        # Reset is_replayed for second replay
        entry.is_replayed = False
        entry.save()

        run_id_2 = entry.replay()

        # Run IDs should be different
        self.assertNotEqual(run_id_1, run_id_2)
        self.assertTrue(run_id_1.startswith("replay-"))
        self.assertTrue(run_id_2.startswith("replay-"))


class TestDeadLetterEntryQueries(TestCase):
    def test_filter_by_workflow_id(self):
        DeadLetterEntry.add_entry(
            workflow_id="workflow-a",
            run_id="run-1",
            payload={},
            error_message="Error",
        )
        DeadLetterEntry.add_entry(
            workflow_id="workflow-b",
            run_id="run-2",
            payload={},
            error_message="Error",
        )
        DeadLetterEntry.add_entry(
            workflow_id="workflow-a",
            run_id="run-3",
            payload={},
            error_message="Error",
        )

        workflow_a_entries = DeadLetterEntry.objects.filter(
            workflow_id="workflow-a"
        )
        self.assertEqual(workflow_a_entries.count(), 2)

    def test_filter_by_is_replayed(self):
        entry1 = DeadLetterEntry.add_entry(
            workflow_id="workflow",
            run_id="run-1",
            payload={},
            error_message="Error",
        )
        DeadLetterEntry.add_entry(
            workflow_id="workflow",
            run_id="run-2",
            payload={},
            error_message="Error",
        )

        # Mark one as replayed
        entry1.is_replayed = True
        entry1.replayed_at = timezone.now()
        entry1.save()

        unreplayed = DeadLetterEntry.objects.filter(is_replayed=False)
        self.assertEqual(unreplayed.count(), 1)
        self.assertEqual(unreplayed.first().run_id, "run-2")


if __name__ == "__main__":
    unittest.main()
