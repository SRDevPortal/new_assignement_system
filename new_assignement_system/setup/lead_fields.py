from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


ASSIGNMENT_STAGES = (
	"Waiting for Metadata",
	"Waiting for Dedupe",
	"Ready",
	"Queued",
	"Processing",
	"Waiting for Agent",
	"Capacity Hold",
	"Assigned",
	"No Matching Rule",
	"Skipped Duplicate",
	"Failed",
	"Cancelled",
	"Review Required",
)


def apply() -> bool:
	if not frappe.db.exists("DocType", "CRM Lead"):
		return False

	meta = frappe.get_meta("CRM Lead")
	anchor = "sr_merged_into" if meta.has_field("sr_merged_into") else meta.fields[-1].fieldname
	create_custom_fields(
		{
			"CRM Lead": [
				{
					"fieldname": "sr_assignment_tab",
					"label": "Assignment Processing",
					"fieldtype": "Tab Break",
					"insert_after": anchor,
					"module": "New Assignement System",
				},
				{
					"fieldname": "sr_assignment_stage",
					"label": "Assignment Stage",
					"fieldtype": "Select",
					"options": "\n" + "\n".join(ASSIGNMENT_STAGES),
					"insert_after": "sr_assignment_tab",
					"read_only": 1,
					"in_list_view": 1,
					"in_standard_filter": 1,
					"module": "New Assignement System",
				},
				{
					"fieldname": "sr_assignment_reason",
					"label": "Assignment Reason",
					"fieldtype": "Small Text",
					"insert_after": "sr_assignment_stage",
					"read_only": 1,
					"module": "New Assignement System",
				},
				{
					"fieldname": "sr_assignment_queued_at",
					"label": "Assignment Queued At",
					"fieldtype": "Datetime",
					"insert_after": "sr_assignment_reason",
					"read_only": 1,
					"module": "New Assignement System",
				},
				{
					"fieldname": "sr_assignment_last_attempt_at",
					"label": "Last Assignment Attempt At",
					"fieldtype": "Datetime",
					"insert_after": "sr_assignment_queued_at",
					"read_only": 1,
					"module": "New Assignement System",
				},
				{
					"fieldname": "sr_assignment_next_attempt_at",
					"label": "Next Assignment Attempt At",
					"fieldtype": "Datetime",
					"insert_after": "sr_assignment_last_attempt_at",
					"read_only": 1,
					"module": "New Assignement System",
				},
				{
					"fieldname": "sr_assignment_completed_at",
					"label": "Assignment Completed At",
					"fieldtype": "Datetime",
					"insert_after": "sr_assignment_next_attempt_at",
					"read_only": 1,
					"module": "New Assignement System",
				},
				{
					"fieldname": "sr_assignment_attempts",
					"label": "Assignment Attempts",
					"fieldtype": "Int",
					"default": "0",
					"insert_after": "sr_assignment_completed_at",
					"read_only": 1,
					"module": "New Assignement System",
				},
				{
					"fieldname": "sr_assignment_rule",
					"label": "Matched Assignment Rule",
					"fieldtype": "Link",
					"options": "New Assignement System Rule",
					"insert_after": "sr_assignment_attempts",
					"read_only": 1,
					"module": "New Assignement System",
				},
				{
					"fieldname": "sr_assignment_error",
					"label": "Assignment Error",
					"fieldtype": "Small Text",
					"insert_after": "sr_assignment_rule",
					"read_only": 1,
					"module": "New Assignement System",
				},
			]
		},
		ignore_validate=True,
		update=True,
	)
	_ensure_pipeline_visibility()
	return True


def _ensure_pipeline_visibility() -> None:
	name = frappe.db.get_value("Custom Field", {"dt": "CRM Lead", "fieldname": "sr_lead_pipeline"}, "name")
	if not name:
		return
	field = frappe.get_doc("Custom Field", name)
	changed = False
	for key in ("in_list_view", "in_standard_filter"):
		if not field.get(key):
			field.set(key, 1)
			changed = True
	if changed:
		field.save(ignore_permissions=True)
