from __future__ import annotations

import frappe

from new_assignement_system.engine.context import get_lead_context, get_pipeline
from new_assignement_system.engine.service import assign_lead, clear_lead_assignment, reassign_lead
from new_assignement_system.integrations.role_permissions import (
	agent_allowed_for_pipeline,
	ensure_can_manage_assignment,
	ensure_can_manage_lead,
	ensure_target_in_managed_team,
)
from new_assignement_system.settings import get_settings


def _as_list(value) -> list[str]:
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except Exception:
			value = [item.strip() for item in value.split(",") if item.strip()]
	if not isinstance(value, list):
		return []
	return [item.get("name") if isinstance(item, dict) else item for item in value if item]


@frappe.whitelist()
def assign_crm_leads(leads, new_owner: str) -> dict:
	ensure_can_manage_assignment()
	ensure_target_in_managed_team(new_owner)

	names = _as_list(leads)
	if not names:
		frappe.throw("Select at least one CRM Lead.")
	if not frappe.db.exists("User", {"name": new_owner, "enabled": 1}):
		frappe.throw("Invalid or disabled user selected.")

	for lead in names:
		ensure_can_manage_lead(lead)
		row = get_lead_context(lead)
		pipeline = get_pipeline(row)
		if pipeline and not agent_allowed_for_pipeline(new_owner, pipeline):
			frappe.throw(
				frappe._("Agent <b>{0}</b> is not allowed for pipeline <b>{1}</b>.").format(
					new_owner,
					pipeline,
				),
				title="Assignment Not Allowed",
			)

	settings = get_settings()
	if len(names) > int(settings.bulk_inline_limit or 20):
		frappe.enqueue(
			"new_assignement_system.jobs.bulk_assign",
			queue=settings.bulk_queue,
			timeout=1800,
			leads=names,
			new_owner=new_owner,
			reason="Manual bulk assignment",
		)
		return {"status": "queued", "count": len(names)}

	for lead in names:
		assign_lead(
			lead,
			new_owner,
			reason="Manual assignment",
			triggered_by=frappe.session.user,
			ignore_permissions=True,
		)
	return {"status": "ok", "count": len(names)}


@frappe.whitelist()
def clear_crm_leads(leads) -> dict:
	ensure_can_manage_assignment()
	names = _as_list(leads)
	if not names:
		frappe.throw("Select at least one CRM Lead.")

	for lead in names:
		ensure_can_manage_lead(lead)

	settings = get_settings()
	if len(names) > int(settings.bulk_inline_limit or 20):
		frappe.enqueue(
			"new_assignement_system.jobs.bulk_clear",
			queue=settings.bulk_queue,
			timeout=1800,
			leads=names,
			reason="Manual bulk clear",
		)
		return {"status": "queued", "count": len(names)}

	for lead in names:
		clear_lead_assignment(lead, reason="Manual clear", triggered_by=frappe.session.user)
	return {"status": "ok", "count": len(names)}


@frappe.whitelist()
def reassign_crm_leads(leads, new_owner: str) -> dict:
	return assign_crm_leads(leads, new_owner)

 
# Backward-compatible names for existing callers.
assign_crm_lead_owner = assign_crm_leads
clear_crm_lead_owner = clear_crm_leads

