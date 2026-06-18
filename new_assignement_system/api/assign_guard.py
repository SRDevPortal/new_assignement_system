from __future__ import annotations

import frappe
from frappe.utils import cstr

from new_assignement_system.api.manual import assign_crm_leads, clear_crm_leads
from new_assignement_system.integrations.role_permissions import ensure_can_manage_assignment
from new_assignement_system.settings import get_settings


def _is_crm_lead(doctype: str | None) -> bool:
	return cstr(doctype) == "CRM Lead"


@frappe.whitelist()
def add(args=None):
	args = args or frappe.local.form_dict.get("args")
	data = frappe.parse_json(args) if args else {}
	doctype = frappe.form_dict.get("reference_type") or data.get("doctype")
	name = frappe.form_dict.get("reference_name") or data.get("name")

	if _is_crm_lead(doctype) and get_settings().enforce_team_leader_guard:
		ensure_can_manage_assignment()
		assign_to = frappe.parse_json(data.get("assign_to") or [])
		if len(assign_to) != 1:
			frappe.throw("CRM Lead can have exactly one lead owner.")
		return assign_crm_leads([name], assign_to[0])

	from frappe.desk.form import assign_to as core

	return core.add(args=args)


@frappe.whitelist()
def remove(doctype, name, assign_to):
	if _is_crm_lead(doctype) and get_settings().enforce_team_leader_guard:
		ensure_can_manage_assignment()
		return clear_crm_leads([name])

	from frappe.desk.form import assign_to as core

	return core.remove(doctype, name, assign_to)


@frappe.whitelist()
def clear(doctype, name):
	if _is_crm_lead(doctype) and get_settings().enforce_team_leader_guard:
		ensure_can_manage_assignment()
		return clear_crm_leads([name])

	from frappe.desk.form import assign_to as core

	return core.clear(doctype, name)

