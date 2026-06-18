from __future__ import annotations

import frappe


def on_trash(doc, method: str | None = None) -> None:
	if doc.reference_type != "CRM Lead" or not doc.reference_name:
		return
	if getattr(frappe.flags, "new_assignement_system_clear_in_progress", False):
		return

	owner = frappe.db.get_value("CRM Lead", doc.reference_name, "lead_owner")
	if owner and doc.allocated_to and owner == doc.allocated_to:
		try:
			frappe.db.delete(
				"DocShare",
				{
					"share_doctype": "CRM Lead",
					"share_name": doc.reference_name,
					"user": doc.allocated_to,
				},
			)
		except Exception:
			pass

