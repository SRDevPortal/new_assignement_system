from unittest import TestCase
from unittest.mock import patch

from new_assignement_system.integrations.dedupe import (
	dedupe_ready_sql_conditions,
	is_dedupe_ready,
	should_skip_lead,
)


class TestDedupeIntegration(TestCase):
	def test_pending_lead_is_not_ready(self):
		with patch(
			"new_assignement_system.integrations.dedupe._has_lead_column",
			return_value=True,
		):
			self.assertFalse(
				is_dedupe_ready(
					{
						"sr_mobile_norm": "9876543210",
						"sr_dedupe_pending": 1,
						"sr_dedupe_status": "Pending",
					}
				)
			)

	def test_merge_master_is_ready(self):
		with patch(
			"new_assignement_system.integrations.dedupe._has_lead_column",
			return_value=True,
		):
			self.assertTrue(
				is_dedupe_ready(
					{
						"sr_mobile_norm": "9876543210",
						"sr_dedupe_pending": 0,
						"sr_dedupe_status": "Master",
					}
				)
			)

	def test_unscanned_normalized_mobile_is_blocked(self):
		with patch(
			"new_assignement_system.integrations.dedupe._has_lead_column",
			return_value=True,
		):
			skip, reason = should_skip_lead(
				{
					"sr_mobile_norm": "9876543210",
					"sr_dedupe_pending": 0,
					"sr_dedupe_status": None,
				}
			)

		self.assertTrue(skip)
		self.assertEqual(reason, "Lead is waiting for dedupe")

	def test_sql_conditions_require_canonical_completed_lead(self):
		with patch(
			"new_assignement_system.integrations.dedupe._has_lead_column",
			return_value=True,
		):
			conditions = dedupe_ready_sql_conditions()

		self.assertIn("sr_is_archived = 0", conditions)
		self.assertIn("sr_is_duplicate = 0", conditions)
		self.assertIn("sr_dedupe_pending = 0", conditions)
		self.assertIn(
			"sr_dedupe_status in ('Master', 'Completed', 'Skipped')",
			conditions,
		)
