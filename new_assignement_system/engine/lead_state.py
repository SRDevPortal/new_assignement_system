from __future__ import annotations

import frappe
from frappe.utils import add_to_date, now_datetime


def set_assignment_state(
	lead: str,
	stage: str,
	*,
	reason: str | None = None,
	rule: str | None = None,
	error: str | None = None,
	increment_attempts: bool = False,
	retry_seconds: int | None = None,
) -> None:
	if not lead or not frappe.db.exists("CRM Lead", lead) or not _has_field("sr_assignment_stage"):
		return

	now = now_datetime()
	values = {
		"sr_assignment_stage": stage,
		"sr_assignment_reason": reason,
		"sr_assignment_error": error,
	}
	if rule is not None:
		values["sr_assignment_rule"] = rule
	if stage in {"Waiting for Dedupe", "Ready", "Queued"}:
		values["sr_assignment_queued_at"] = now
	if stage == "Processing" or increment_attempts:
		values["sr_assignment_last_attempt_at"] = now
	if retry_seconds is not None:
		values["sr_assignment_next_attempt_at"] = add_to_date(now, seconds=max(0, int(retry_seconds)))
	elif stage in {"Assigned", "Skipped Duplicate", "Cancelled", "No Matching Rule"}:
		values["sr_assignment_next_attempt_at"] = None
	if stage in {"Assigned", "Skipped Duplicate", "Cancelled"}:
		values["sr_assignment_completed_at"] = now
	if increment_attempts and _has_field("sr_assignment_attempts"):
		attempts = frappe.db.get_value("CRM Lead", lead, "sr_assignment_attempts") or 0
		values["sr_assignment_attempts"] = int(attempts) + 1

	values = {field: value for field, value in values.items() if _has_field(field)}
	frappe.db.set_value("CRM Lead", lead, values, update_modified=False)


def _has_field(fieldname: str) -> bool:
	try:
		return bool(frappe.db.has_column("CRM Lead", fieldname))
	except Exception:
		return False
