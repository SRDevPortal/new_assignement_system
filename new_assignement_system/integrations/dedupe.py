from __future__ import annotations

import re

import frappe
from frappe.utils import cint


def should_skip_lead(row: dict) -> tuple[bool, str | None]:
	if cint(row.get("converted")):
		return True, "Lead is converted"
	if cint(row.get("sr_is_archived")):
		return True, "Lead is archived"
	if cint(row.get("sr_is_duplicate")):
		return True, "Lead is marked duplicate"
	if row.get("sr_duplicate_of_name") or row.get("sr_duplicate_of"):
		return True, "Lead points to a duplicate primary"
	if str(row.get("sr_dedupe_result") or "").strip() == "Duplicate":
		return True, "Dedupe result is Duplicate"
	return False, None


def allowed_results(value) -> set[str]:
	if isinstance(value, str):
		values = re.split(r"[\n,]+", value)
	elif isinstance(value, (list, tuple, set)):
		values = value
	else:
		values = []
	return {str(item).strip() for item in values if str(item).strip() and str(item).strip() != "Duplicate"}


def evaluate_assignment_readiness(row: dict, settings) -> tuple[bool, bool, str | None]:
	"""Return allowed, terminal, reason using CRM Lead fields only."""
	skip, reason = should_skip_lead(row)
	if skip:
		return False, True, reason
	if not cint(settings.get("enable_dedupe_readiness_check")):
		return True, False, None

	if not _has_field("sr_dedupe_stage"):
		if str(settings.get("dedupe_missing_field_behavior") or "Hold") == "Proceed":
			return True, False, None
		return False, False, "Dedupe readiness field is not installed"

	stage = str(row.get("sr_dedupe_stage") or "").strip()
	result = str(row.get("sr_dedupe_result") or "").strip()
	if not stage:
		stage, result = _legacy_state(row.get("sr_dedupe_status"))

	if stage == "Failed":
		return False, False, "Dedupe failed"
	if stage == "Waiting for Metadata":
		return False, False, "Waiting for dedupe metadata"

	required = str(settings.get("dedupe_required_stage") or "Completed").strip()
	ranks = {"Pending": 1, "Processing": 2, "Completed": 3}
	if ranks.get(stage, 0) < ranks.get(required, 3):
		return False, False, f"Waiting for dedupe stage {required}"

	if stage == "Completed":
		if result == "Duplicate":
			return False, True, "Dedupe result is Duplicate"
		allowed = allowed_results(settings.get("dedupe_allowed_results"))
		if result not in allowed:
			return False, False, f"Dedupe result {result or 'blank'} is not allowed"

	return True, False, None


def _has_field(fieldname: str) -> bool:
	try:
		return bool(frappe.db.has_column("CRM Lead", fieldname))
	except Exception:
		return False


def _legacy_state(status) -> tuple[str, str]:
	status = str(status or "").strip()
	return {
		"Pending": ("Pending", ""),
		"Processing": ("Processing", ""),
		"Master": ("Completed", "Primary"),
		"Duplicate": ("Completed", "Duplicate"),
		"Skipped": ("Completed", "Skipped"),
		"Failed": ("Failed", ""),
	}.get(status, ("", ""))
