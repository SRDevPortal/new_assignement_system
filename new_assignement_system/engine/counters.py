from __future__ import annotations

import frappe
from frappe.utils import now_datetime


def ensure_agent_state(agent: str, team: str | None = None) -> str:
	name = agent
	if frappe.db.exists("New Assignement System Agent State", name):
		return name

	doc = frappe.get_doc(
		{
			"doctype": "New Assignement System Agent State",
			"name": name,
			"agent": agent,
			"active": 1,
			"weight": 1,
			"capacity": 0,
			"current_open_leads": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def increment_agent(agent: str | None, team: str | None = None, *, reassigned: bool = False) -> None:
	if not agent:
		return
	name = ensure_agent_state(agent, team)
	now = now_datetime()
	field = "today_reassigned_count" if reassigned else "today_assigned_count"
	frappe.db.sql(
		f"""
		update `tabNew Assignement System Agent State`
		set current_open_leads = ifnull(current_open_leads, 0) + 1,
			{field} = ifnull({field}, 0) + 1,
			last_assigned_at = %s,
			load_score = case
				when ifnull(capacity, 0) > 0
				then (ifnull(current_open_leads, 0) + 1) / (capacity * ifnull(nullif(weight, 0), 1))
				else (ifnull(current_open_leads, 0) + 1) / ifnull(nullif(weight, 0), 1)
			end,
			modified = %s,
			modified_by = %s
		where name = %s
		""",
		(now, now, frappe.session.user, name),
	)


def decrement_agent(agent: str | None, team: str | None = None) -> None:
	if not agent:
		return
	name = _find_state(agent, team)
	if not name:
		return
	now = now_datetime()
	frappe.db.sql(
		"""
		update `tabNew Assignement System Agent State`
		set current_open_leads = greatest(ifnull(current_open_leads, 0) - 1, 0),
			last_released_at = %s,
			load_score = case
				when ifnull(capacity, 0) > 0
				then greatest(ifnull(current_open_leads, 0) - 1, 0) / (capacity * ifnull(nullif(weight, 0), 1))
				else greatest(ifnull(current_open_leads, 0) - 1, 0) / ifnull(nullif(weight, 0), 1)
			end,
			modified = %s,
			modified_by = %s
		where name = %s
		""",
		(now, now, frappe.session.user, name),
	)


def _find_state(agent: str, team: str | None = None) -> str | None:
	filters = {"agent": agent}
	if team:
		filters["team"] = team
	name = frappe.db.get_value("New Assignement System Agent State", filters, "name")
	if name:
		return name
	return frappe.db.get_value(
		"New Assignement System Agent State",
		{"agent": agent, "current_open_leads": [">", 0]},
		"name",
		order_by="current_open_leads desc",
	)


def rebuild_all() -> int:
	if not frappe.db.exists("DocType", "New Assignement System Agent State"):
		return 0

	frappe.db.sql(
		"""
		update `tabNew Assignement System Agent State`
		set current_open_leads = 0,
			load_score = 0
		"""
	)
	fields = ["lead_owner"]

	rows = frappe.get_all(
		"CRM Lead",
		filters={"lead_owner": ["is", "set"], "converted": 0},
		fields=fields,
		limit_page_length=0,
	)
	count = 0
	for row in rows:
		increment_agent(row.lead_owner)
		count += 1
	return count


def sync_from_teams() -> int:
	return 0
