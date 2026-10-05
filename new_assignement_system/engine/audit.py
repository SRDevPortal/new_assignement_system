from __future__ import annotations

import frappe

from new_assignement_system.number_privacy import sanitize_for_storage


def log_assignment(
	*,
	lead: str,
	action: str,
	old_owner: str | None = None,
	new_owner: str | None = None,
	team: str | None = None,
	rule: str | None = None,
	strategy: str | None = None,
	queue: str | None = None,
	triggered_by: str | None = None,
	reason: str | None = None,
	metadata_snapshot: str | None = None,
	status: str = "Success",
	error: str | None = None,
) -> str | None:
	if not frappe.db.exists("DocType", "New Assignement System Log"):
		return None

	doc = frappe.get_doc(
		{
			"doctype": "New Assignement System Log",
			"lead": lead,
			"action": action,
			"status": status,
			"old_owner": old_owner,
			"new_owner": new_owner,
			"team": team,
			"rule": rule,
			"strategy": strategy,
			"queue": queue,
			"triggered_by": triggered_by or frappe.session.user,
			"reason": sanitize_for_storage(reason),
			"metadata_snapshot": metadata_snapshot,
			"error": sanitize_for_storage(error),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name

