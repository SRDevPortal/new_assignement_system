from __future__ import annotations

import frappe


DEFAULT_SETTINGS = {
	"enabled": 1,
	"queue_enabled": 1,
	"auto_assign_on_insert": 1,
	"inline_assign_on_insert": 1,
	"override_api_owner_when_rule_matches": 0,
	"auto_reassign_on_update": 0,
	"auto_unassign_on_update": 1,
	"enable_metadata_based_assignment": 0,
	"allow_fallback_without_active_session": 0,
	"disable_manual_assign_to": 1,
	"sync_todo": 1,
	"sync_docshare": 1,
	"notify_manual_assign": 0,
	"default_queue": "lead_assignment_short",
	"bulk_queue": "lead_assignment_bulk",
	"scheduler_queue": "lead_assignment_scheduler",
	"bulk_inline_limit": 20,
	"queue_batch_size": 100,
	"default_strategy": "Balanced Load",
	"fallback_user": None,
	"stale_reassignment_enabled": 0,
	"stale_after_minutes": 120,
}


def get_settings() -> frappe._dict:
	data = frappe._dict(DEFAULT_SETTINGS.copy())
	if not frappe.db.exists("DocType", "New Assignement System Settings"):
		return data

	try:
		doc = frappe.get_single("New Assignement System Settings")
	except Exception:
		return data

	for key in DEFAULT_SETTINGS:
		value = doc.get(key)
		if value not in (None, ""):
			data[key] = value
	return data


def is_enabled() -> bool:
	return bool(get_settings().enabled)
