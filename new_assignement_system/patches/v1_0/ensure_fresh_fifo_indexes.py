from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.exists("DocType", "CRM Lead"):
		return
	if not all(frappe.db.has_column("CRM Lead", field) for field in ["status", "lead_owner", "creation"]):
		return

	previous = getattr(frappe.flags, "in_migrate", False)
	frappe.flags.in_migrate = True
	try:
		frappe.db.add_index(
			"CRM Lead",
			["status", "lead_owner", "creation"],
			index_name="idx_crmlead_fresh_fifo",
		)
	finally:
		frappe.flags.in_migrate = previous
