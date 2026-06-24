from __future__ import annotations

import frappe


def has_team_field() -> bool:
	try:
		return frappe.db.has_column("CRM Lead", "team")
	except Exception:
		return False


def get_team_for_user(user: str | None) -> str | None:
	if not user or user == "Guest":
		return None
	if not has_team_field():
		return None
	if not frappe.db.exists("DocType", "Team") or not frappe.db.exists("DocType", "Team User"):
		return None

	try:
		from team.api.team_logic import get_team_for_user as team_app_get_team_for_user
	except Exception:
		return None

	return team_app_get_team_for_user(user)


def get_active_team_members(team: str | None) -> list[str]:
	if not team:
		return []
	if not frappe.db.exists("DocType", "Team") or not frappe.db.exists("DocType", "Team User"):
		return []
	if not frappe.db.exists("Team", {"name": team, "is_active": 1}):
		return []

	rows = frappe.db.sql(
		"""
		select tu.user
		from `tabTeam User` tu
		inner join `tabTeam` t on t.name = tu.parent
		where tu.parent = %s
		  and tu.parenttype = 'Team'
		  and ifnull(tu.is_active, 1) = 1
		  and ifnull(t.is_active, 1) = 1
		  and tu.user is not null
		  and tu.user != ''
		order by tu.idx asc
		""",
		team,
		as_dict=True,
	)
	return [row.user for row in rows]
