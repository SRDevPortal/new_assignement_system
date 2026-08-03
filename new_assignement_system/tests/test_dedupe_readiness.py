from unittest import TestCase
from unittest.mock import patch

import frappe

from new_assignement_system.integrations.dedupe import allowed_results, evaluate_assignment_readiness


def settings(**values):
	data = {
		"enable_dedupe_readiness_check": 1,
		"dedupe_required_stage": "Completed",
		"dedupe_allowed_results": "Primary\nSkipped",
		"dedupe_missing_field_behavior": "Hold",
	}
	data.update(values)
	return frappe._dict(data)


class TestDedupeReadiness(TestCase):
	def test_completed_primary_is_ready(self):
		with patch("new_assignement_system.integrations.dedupe._has_field", return_value=True):
			self.assertEqual(
				evaluate_assignment_readiness(
					{"sr_dedupe_stage": "Completed", "sr_dedupe_result": "Primary"},
					settings(),
				),
				(True, False, None),
			)

	def test_pending_waits_when_completed_is_required(self):
		with patch("new_assignement_system.integrations.dedupe._has_field", return_value=True):
			allowed, terminal, reason = evaluate_assignment_readiness(
				{"sr_dedupe_stage": "Pending"}, settings()
			)
		self.assertFalse(allowed)
		self.assertFalse(terminal)
		self.assertIn("Completed", reason)

	def test_pending_can_be_selected_explicitly(self):
		with patch("new_assignement_system.integrations.dedupe._has_field", return_value=True):
			self.assertEqual(
				evaluate_assignment_readiness(
					{"sr_dedupe_stage": "Pending"}, settings(dedupe_required_stage="Pending")
				),
				(True, False, None),
			)

	def test_duplicate_is_always_terminal(self):
		with patch("new_assignement_system.integrations.dedupe._has_field", return_value=True):
			allowed, terminal, reason = evaluate_assignment_readiness(
				{"sr_dedupe_stage": "Completed", "sr_dedupe_result": "Duplicate"}, settings()
			)
		self.assertFalse(allowed)
		self.assertTrue(terminal)
		self.assertIn("Duplicate", reason)

	def test_legacy_master_state_is_accepted(self):
		with patch("new_assignement_system.integrations.dedupe._has_field", return_value=True):
			self.assertEqual(
				evaluate_assignment_readiness({"sr_dedupe_status": "Master"}, settings()),
				(True, False, None),
			)

	def test_missing_field_can_proceed_only_when_configured(self):
		with patch("new_assignement_system.integrations.dedupe._has_field", return_value=False):
			self.assertFalse(evaluate_assignment_readiness({}, settings())[0])
			self.assertTrue(
				evaluate_assignment_readiness({}, settings(dedupe_missing_field_behavior="Proceed"))[0]
			)

	def test_duplicate_cannot_be_added_to_allowed_results(self):
		self.assertEqual(allowed_results("Primary\nDuplicate,Skipped"), {"Primary", "Skipped"})
