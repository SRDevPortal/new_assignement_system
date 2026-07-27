from datetime import datetime
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from new_assignement_system.jobs import _should_retry_assignment, process_assignment_queue_item


class TestQueueRetry(TestCase):
	def test_retryable_availability_skip_stays_in_queue(self):
		result = {
			"status": "skipped",
			"reason": "No eligible agent for rule Night Leads",
			"retryable": True,
		}

		self.assertTrue(_should_retry_assignment(result))

	def test_permanent_skip_is_terminal(self):
		result = {
			"status": "skipped",
			"reason": "No assignment rule matched",
			"retryable": False,
		}

		self.assertFalse(_should_retry_assignment(result))

	def test_success_is_not_retried(self):
		self.assertFalse(_should_retry_assignment({"status": "ok", "retryable": True}))

	@patch("new_assignement_system.jobs.frappe")
	@patch("new_assignement_system.jobs.now_datetime", return_value=datetime(2026, 7, 27, 9, 0))
	@patch("new_assignement_system.jobs.auto_assign_lead")
	@patch("new_assignement_system.jobs.try_lock")
	def test_worker_keeps_offline_lead_in_retry(
		self,
		try_lock: MagicMock,
		auto_assign_lead: MagicMock,
		_now_datetime: MagicMock,
		mock_frappe: MagicMock,
	):
		try_lock.return_value = frappe._dict(
			lead="CRM-LEAD-0001",
			event_type="Insert",
			attempts=1,
		)
		auto_assign_lead.return_value = {
			"status": "skipped",
			"reason": "No eligible agent for rule Night Leads",
			"retryable": True,
		}

		process_assignment_queue_item("NAS-Q-0001")

		values = mock_frappe.db.set_value.call_args.args[2]
		self.assertEqual(values["status"], "Retry")
		self.assertEqual(values["error"], "No eligible agent for rule Night Leads")
		self.assertIsNotNone(values["next_retry_at"])
