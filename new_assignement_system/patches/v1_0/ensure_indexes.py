from __future__ import annotations

import frappe


def execute() -> None:
	ensure_crm_lead_indexes()
	ensure_todo_indexes()
	ensure_assignment_indexes()


def _add_index(doctype: str, fields: list[str], index_name: str) -> None:
	if not frappe.db.exists("DocType", doctype):
		return
	if not all(frappe.db.has_column(doctype, field) for field in fields):
		return

	previous = getattr(frappe.flags, "in_migrate", False)
	frappe.flags.in_migrate = True
	try:
		frappe.db.add_index(doctype, fields, index_name=index_name)
	finally:
		frappe.flags.in_migrate = previous


def ensure_crm_lead_indexes() -> None:
	_add_index("CRM Lead", ["lead_owner"], "idx_crmlead_assignment_owner")
	_add_index("CRM Lead", ["lead_owner", "status"], "idx_crmlead_assignment_owner_status")
	_add_index("CRM Lead", ["lead_owner", "sr_lead_pipeline"], "idx_crmlead_assignment_owner_pipeline")
	_add_index("CRM Lead", ["sr_lead_pipeline", "status", "converted"], "idx_crmlead_assignment_pipeline_status")
	_add_index("CRM Lead", ["source", "status", "converted"], "idx_crmlead_assignment_source_status")
	_add_index("CRM Lead", ["modified"], "idx_crmlead_assignment_modified")


def ensure_todo_indexes() -> None:
	_add_index("ToDo", ["reference_type", "reference_name", "status"], "idx_todo_assignment_reference")
	_add_index("ToDo", ["reference_type", "allocated_to", "status"], "idx_todo_assignment_allocated")


def ensure_assignment_indexes() -> None:
	_add_index("New Assignement System Queue", ["status", "next_retry_at"], "idx_claq_status_retry")
	_add_index("New Assignement System Queue", ["lead", "status"], "idx_claq_lead_status")
	_add_index("New Assignement System Queue", ["priority", "status", "creation"], "idx_claq_priority_status")
	_add_index("New Assignement System Agent State", ["active", "load_score"], "idx_nas_state_load")
	_add_index("New Assignement System Agent State", ["agent"], "idx_claas_agent")
	_add_index("New Assignement System Log", ["lead"], "idx_clal_lead")
	_add_index("New Assignement System Log", ["new_owner", "creation"], "idx_clal_owner_creation")
	_add_index("New Assignement System Log", ["action", "creation"], "idx_clal_action_creation")
