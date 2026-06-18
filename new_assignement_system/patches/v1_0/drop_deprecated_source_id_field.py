from __future__ import annotations

import frappe


def execute() -> None:
	doctype = "New Assignement System Rule"
	fieldname = "source_id"

	docfield = frappe.db.exists("DocField", {"parent": doctype, "fieldname": fieldname})
	if docfield:
		frappe.delete_doc("DocField", docfield, ignore_permissions=True, force=True)

	if frappe.db.has_column(doctype, fieldname):
		frappe.db.sql_ddl(f"alter table `tab{doctype}` drop column `{fieldname}`")

