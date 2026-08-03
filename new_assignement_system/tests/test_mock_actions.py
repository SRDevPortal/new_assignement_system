from datetime import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from new_assignement_system.integrations.dedupe import evaluate_assignment_readiness
from new_assignement_system.jobs import _reconcile_assigned_duplicates, release_assignment_waiting_leads


def settings(**values):
	data = {
		"enabled": 1,
		"queue_enabled": 1,
		"queue_batch_size": 10,
		"enable_dedupe_readiness_check": 1,
		"dedupe_required_stage": "Completed",
		"dedupe_allowed_results": "Primary",
		"dedupe_missing_field_behavior": "Proceed",
		"assignment_readiness_retry_seconds": 60,
	}
	data.update(values)
	return frappe._dict(data)


class TestAssignmentMockActions(TestCase):
	def test_action_pending_dedupe_holds_assignment(self):
		with patch("new_assignement_system.integrations.dedupe._has_field", return_value=True):
			allowed, terminal, reason = evaluate_assignment_readiness(
				{"sr_dedupe_stage": "Pending"}, settings()
			)

		self.assertFalse(allowed)
		self.assertFalse(terminal)
		self.assertEqual(reason, "Waiting for dedupe stage Completed")

	def test_action_completed_primary_allows_assignment(self):
		with patch("new_assignement_system.integrations.dedupe._has_field", return_value=True):
			self.assertEqual(
				evaluate_assignment_readiness(
					{"sr_dedupe_stage": "Completed", "sr_dedupe_result": "Primary"}, settings()
				),
				(True, False, None),
			)

	def test_action_completed_duplicate_blocks_assignment(self):
		with patch("new_assignement_system.integrations.dedupe._has_field", return_value=True):
			allowed, terminal, reason = evaluate_assignment_readiness(
				{"sr_dedupe_stage": "Completed", "sr_dedupe_result": "Duplicate"}, settings()
			)

		self.assertFalse(allowed)
		self.assertTrue(terminal)
		self.assertEqual(reason, "Dedupe result is Duplicate")

	def test_action_independent_release_enqueues_ready_lead(self):
		row = frappe._dict(name="MOCK-LEAD-1")
		db = MagicMock()
		db.has_column.return_value = True
		db.sql.return_value = [row]
		db.exists.return_value = True
		fake_frappe = SimpleNamespace(db=db)
		with (
			patch("new_assignement_system.jobs.get_settings", return_value=settings()),
			patch("new_assignement_system.jobs.now_datetime", return_value=datetime(2026, 8, 3, 12, 0, 0)),
			patch("new_assignement_system.jobs.frappe", fake_frappe),
			patch("new_assignement_system.jobs._reconcile_assigned_duplicates"),
			patch("new_assignement_system.jobs._reconcile_owned_primary_states"),
			patch(
				"new_assignement_system.jobs.get_lead_context",
				return_value=frappe._dict(sr_dedupe_stage="Completed", sr_dedupe_result="Primary"),
			),
			patch("new_assignement_system.jobs.evaluate_assignment_readiness", return_value=(True, False, None)),
			patch("new_assignement_system.jobs.set_assignment_state") as set_state,
			patch("new_assignement_system.engine.queue.enqueue_lead", return_value="MOCK-QUEUE-1") as enqueue,
		):
			released = release_assignment_waiting_leads(limit=1)

		self.assertEqual(released, 1)
		set_state.assert_any_call("MOCK-LEAD-1", "Ready", reason="Assignment prerequisites are ready")
		enqueue.assert_called_once_with("MOCK-LEAD-1", event_type="Insert", process_now=True)

	def test_action_assigned_duplicate_requires_review_without_unassigning(self):
		db = MagicMock()
		db.has_column.return_value = True
		db.sql.return_value = [frappe._dict(name="MOCK-LEAD-OWNED")]
		fake_frappe = SimpleNamespace(db=db)
		with (
			patch("new_assignement_system.jobs.frappe", fake_frappe),
			patch("new_assignement_system.jobs.set_assignment_state") as set_state,
		):
			count = _reconcile_assigned_duplicates(1)

		self.assertEqual(count, 1)
		set_state.assert_called_once_with(
			"MOCK-LEAD-OWNED",
			"Review Required",
			reason="Assigned lead was later classified as a duplicate; ownership was preserved",
		)
