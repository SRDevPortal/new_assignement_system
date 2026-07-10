from __future__ import annotations

import frappe
from frappe.utils import cint

FRESH_SLOT_REFILL_STATUS_CHANGE_ONLY = "Status Change Only"
FRESH_SLOT_REFILL_SCHEDULER_ONLY = "Scheduler Only"
FRESH_SLOT_REFILL_BOTH = "Both"
FRESH_SLOT_REFILL_DISABLED = "Disabled"
FRESH_SLOT_REFILL_MODES = {
	FRESH_SLOT_REFILL_STATUS_CHANGE_ONLY,
	FRESH_SLOT_REFILL_SCHEDULER_ONLY,
	FRESH_SLOT_REFILL_BOTH,
	FRESH_SLOT_REFILL_DISABLED,
}
FRESH_SLOT_REFILL_TRIGGER_STATUS_CHANGE = "status_change"
FRESH_SLOT_REFILL_TRIGGER_SCHEDULER = "scheduler"


DEFAULT_SETTINGS = {
	"enabled": 1,
	"queue_enabled": 1,
	"auto_assign_on_insert": 1,
	"inline_assign_on_insert": 1,
	"override_api_owner_when_rule_matches": 0,
	"enable_total_capacity_limit": 1,
	"enable_fresh_lead_limit": 0,
	"enable_fresh_slot_auto_refill": 1,
	"fresh_slot_auto_refill_mode": FRESH_SLOT_REFILL_STATUS_CHANGE_ONLY,
	"fresh_lead_status": "New",
	"fresh_lead_limit_per_agent": 5,
	"auto_reassign_on_update": 0,
	"auto_unassign_on_update": 0,
	"enable_status_based_assignment": 0,
	"enable_metadata_based_assignment": 0,
	"allow_fallback_without_active_session": 0,
	"disable_manual_assign_to": 1,
	"sync_todo": 1,
	"sync_docshare": 1,
	"sync_team_from_lead_owner": 1,
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


def get_fresh_slot_auto_refill_mode(settings: frappe._dict | None = None) -> str:
	settings = settings or get_settings()
	mode = str(settings.get("fresh_slot_auto_refill_mode") or FRESH_SLOT_REFILL_STATUS_CHANGE_ONLY).strip()
	if mode not in FRESH_SLOT_REFILL_MODES:
		return FRESH_SLOT_REFILL_STATUS_CHANGE_ONLY
	return mode


def should_run_fresh_slot_auto_refill(trigger: str, settings: frappe._dict | None = None) -> bool:
	settings = settings or get_settings()
	if not cint(settings.enable_fresh_slot_auto_refill):
		return False

	mode = get_fresh_slot_auto_refill_mode(settings)
	if mode == FRESH_SLOT_REFILL_DISABLED:
		return False
	if trigger == FRESH_SLOT_REFILL_TRIGGER_STATUS_CHANGE:
		return mode in {FRESH_SLOT_REFILL_STATUS_CHANGE_ONLY, FRESH_SLOT_REFILL_BOTH}
	if trigger == FRESH_SLOT_REFILL_TRIGGER_SCHEDULER:
		return mode in {FRESH_SLOT_REFILL_SCHEDULER_ONLY, FRESH_SLOT_REFILL_BOTH}
	return False


def get_status_assignment_rule(status: str | None) -> frappe._dict | None:
	if not status:
		return None
	if not frappe.db.exists("DocType", "New Assignement System Settings"):
		return None
	if not frappe.db.exists("DocType", "New Assignement System Status Assignment User"):
		return None

	try:
		doc = frappe.get_single("New Assignement System Settings")
	except Exception:
		return None

	if not doc.get("enable_status_based_assignment"):
		return None

	status = str(status).strip()
	for row in doc.get("status_assignment_users") or []:
		if row.get("enabled") and str(row.get("lead_status") or "").strip() == status:
			return frappe._dict(
				assign_to_user=row.get("assign_to_user"),
				target_pipeline=row.get("target_pipeline"),
			)
	return None


def get_status_assignment_user(status: str | None) -> str | None:
	rule = get_status_assignment_rule(status)
	return rule.assign_to_user if rule else None
