from __future__ import annotations

import frappe


INDEX_NAME = "idx_crmlead_canonical_fresh_fifo"
FIELDS = [
	"lead_owner",
	"status",
	"converted",
	"sr_is_archived",
	"sr_is_duplicate",
	"sr_dedupe_pending",
	"sr_dedupe_status",
	"creation",
]


def execute() -> None:
	if not frappe.db.exists("DocType", "CRM Lead"):
		return
	if not all(frappe.db.has_column("CRM Lead", fieldname) for fieldname in FIELDS):
		return

	exists = frappe.db.sql(
		"""
		select count(*)
		from information_schema.STATISTICS
		where TABLE_SCHEMA = database()
		  and TABLE_NAME = 'tabCRM Lead'
		  and INDEX_NAME = %s
		""",
		INDEX_NAME,
	)[0][0]
	if exists:
		return

	columns = ", ".join(f"`{fieldname}`" for fieldname in FIELDS)
	frappe.db.sql(
		f"""
		alter table `tabCRM Lead`
		add index `{INDEX_NAME}` ({columns}),
		algorithm=inplace,
		lock=none
		"""
	)
