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
	if team and frappe.db.has_column("New Assignement System Agent State", "team"):
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

	rows = frappe.db.sql(
		"""
		select lead_owner, count(*) as open_leads
		from `tabCRM Lead`
		where lead_owner is not null
		  and lead_owner != ''
		  and ifnull(converted, 0) = 0
		group by lead_owner
		""",
		as_dict=True,
	)
	count = 0
	for row in rows:
		name = ensure_agent_state(row.lead_owner)
		open_leads = int(row.open_leads or 0)
		frappe.db.sql(
			"""
			update `tabNew Assignement System Agent State`
			set current_open_leads = %s,
				load_score = case
					when ifnull(capacity, 0) > 0
					then %s / (capacity * ifnull(nullif(weight, 0), 1))
					else %s / ifnull(nullif(weight, 0), 1)
				end,
				modified = %s,
				modified_by = %s
			where name = %s
			""",
			(open_leads, open_leads, open_leads, now_datetime(), frappe.session.user, name),
		)
		count += open_leads
	return count


def reset_daily_counts() -> None:
	if not frappe.db.exists("DocType", "New Assignement System Agent State"):
		return

	frappe.db.sql(
		"""
		update `tabNew Assignement System Agent State`
		set today_assigned_count = 0,
			today_reassigned_count = 0,
			modified = %s,
			modified_by = %s
		""",
		(now_datetime(), frappe.session.user),
	)


def sync_login_status() -> int:
	if not frappe.db.exists("DocType", "New Assignement System Agent State"):
		return 0

	from new_assignement_system.engine.eligibility import is_user_session_available

	rows = frappe.get_all(
		"New Assignement System Agent State",
		fields=["name", "agent", "active"],
		limit_page_length=0,
	)
	updated = 0
	now = now_datetime()
	for row in rows:
		active = 1 if is_user_session_available(row.agent) else 0
		if int(row.active or 0) == active:
			continue
		frappe.db.set_value(
			"New Assignement System Agent State",
			row.name,
			{
				"active": active,
				"modified": now,
				"modified_by": frappe.session.user,
			},
			update_modified=False,
		)
		updated += 1
	return updated


def sync_from_teams() -> int:
	return 0
