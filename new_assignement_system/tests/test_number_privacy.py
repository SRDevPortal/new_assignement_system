from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import frappe

from new_assignement_system.engine.context import snapshot
from new_assignement_system.number_privacy import (
    project_response,
    sanitize_for_storage,
)


class TestAssignmentNumberPrivacy(unittest.TestCase):
    def test_restricted_response_masks_numbers_without_mutating_source(self):
        raw = {
            "mobile_no": "9876543210",
            "message": "Assignment failed for +91 98765 43210",
            "status": "failed",
        }
        with patch("new_assignement_system.number_privacy.restricted", return_value=True):
            result = project_response(raw)

        self.assertNotIn("9876543210", str(result))
        self.assertEqual(result["mobile_no"], "******3210")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(raw["mobile_no"], "9876543210")

    def test_full_visibility_preserves_response_object(self):
        raw = {"mobile_no": "9876543210"}
        with patch("new_assignement_system.number_privacy.restricted", return_value=False):
            self.assertIs(project_response(raw), raw)

    def test_storage_sanitizer_masks_numbers_when_feature_enabled(self):
        raw = {"error": "Lead 9876543210 failed", "items": ["+91 98765 43210"]}
        with patch("new_assignement_system.number_privacy.enabled", return_value=True):
            result = sanitize_for_storage(raw)

        self.assertNotIn("9876543210", str(result))
        self.assertEqual(raw["error"], "Lead 9876543210 failed")

    def test_storage_sanitizer_preserves_dates_and_long_metadata_ids(self):
        raw = "At 2026-10-05 source 120251580552780012"
        with patch("new_assignement_system.number_privacy.enabled", return_value=True):
            self.assertEqual(sanitize_for_storage(raw), raw)

    def test_storage_sanitizer_preserves_values_when_feature_disabled(self):
        raw = "Lead 9876543210 failed"
        with patch("new_assignement_system.number_privacy.enabled", return_value=False):
            self.assertEqual(sanitize_for_storage(raw), raw)

    def test_assignment_snapshot_excludes_mobile_but_internal_row_keeps_it(self):
        row = frappe._dict(
            name="CRM-LEAD-1",
            lead_owner="agent@example.com",
            mobile_no="9876543210",
            status="Open",
        )
        result = snapshot(row)

        self.assertNotIn("mobile_no", result)
        self.assertEqual(row.mobile_no, "9876543210")

    def test_audit_sanitizes_free_text_before_insert(self):
        from new_assignement_system.engine import audit

        doc = MagicMock()
        fake_frappe = MagicMock()
        fake_frappe.db.exists.return_value = True
        fake_frappe.get_doc.return_value = doc
        fake_frappe.session.user = "Administrator"

        with (
            patch.object(audit, "frappe", fake_frappe),
            patch.object(
                audit,
                "sanitize_for_storage",
                side_effect=lambda value: (
                    value.replace("9876543210", "******3210")
                    if isinstance(value, str)
                    else value
                ),
            ),
        ):
            audit.log_assignment(
                lead="CRM-LEAD-1",
                action="Failed",
                reason="Number 9876543210",
                error="Call 9876543210 failed",
                metadata_snapshot='{"created":"2026-10-05"}',
            )

        values = fake_frappe.get_doc.call_args.args[0]
        self.assertNotIn("9876543210", str(values))
        doc.insert.assert_called_once_with(ignore_permissions=True)

    def test_queue_retry_sanitizes_error_before_storage(self):
        from new_assignement_system.engine import queue

        with (
            patch.object(queue.frappe.db, "set_value") as set_value,
            patch.object(queue, "sanitize_for_storage", return_value="Call ******3210 failed"),
        ):
            queue.mark_retry("QUEUE-1", "Call 9876543210 failed", 1)

        values = set_value.call_args.args[2]
        self.assertEqual(values["error"], "Call ******3210 failed")

    def test_lead_assignment_state_sanitizes_reason_and_error(self):
        from new_assignement_system.engine import lead_state

        with (
            patch.object(lead_state.frappe.db, "exists", return_value=True),
            patch.object(lead_state, "_has_field", return_value=True),
            patch.object(lead_state.frappe.db, "set_value") as set_value,
            patch.object(
                lead_state,
                "sanitize_for_storage",
                side_effect=lambda value: (
                    value.replace("9876543210", "******3210")
                    if isinstance(value, str)
                    else value
                ),
            ),
        ):
            lead_state.set_assignment_state(
                "CRM-LEAD-1",
                "Failed",
                reason="Number 9876543210",
                error="Call 9876543210 failed",
            )

        values = set_value.call_args.args[2]
        self.assertNotIn("9876543210", str(values))

    def test_context_endpoint_uses_browser_projection(self):
        from new_assignement_system.api import context

        self.assertTrue(hasattr(context.get_new_assignement_system_context, "__wrapped__"))
        self.assertTrue(
            hasattr(context.get_new_assignement_system_context.__wrapped__, "__wrapped__")
        )
