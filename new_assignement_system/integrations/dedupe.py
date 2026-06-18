from __future__ import annotations

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
	return False, None

