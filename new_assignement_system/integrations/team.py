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
