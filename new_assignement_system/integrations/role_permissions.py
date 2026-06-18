from __future__ import annotations

from functools import lru_cache

import frappe

REF_DOCTYPE = "CRM Lead"


def _roles_api():
	from sriaas_role_permissions.api import roles

	return roles


def _config_api():
	from sriaas_role_permissions.api import config

	return config


def get_config():
	return _config_api().get_doctype_config(REF_DOCTYPE)


def is_privileged(user: str | None = None) -> bool:
	user = user or frappe.session.user
	try:
		return bool(_roles_api().is_privileged(user, REF_DOCTYPE))
	except Exception:
		return "System Manager" in (frappe.get_roles(user) or [])


def has_team_leader_role(user: str | None = None) -> bool:
	user = user or frappe.session.user
	try:
		return bool(_roles_api().has_team_leader_role(user, REF_DOCTYPE))
	except Exception:
		return "Team Leader" in (frappe.get_roles(user) or [])


def has_agent_role(user: str | None = None) -> bool:
	user = user or frappe.session.user
	try:
		return bool(_roles_api().has_agent_role(user, REF_DOCTYPE))
	except Exception:
		return "Agent" in (frappe.get_roles(user) or [])


def managed_team_names(user: str | None = None) -> set[str]:
	user = user or frappe.session.user
	if not frappe.db.exists("DocType", "Team"):
		return set()

	led = set(frappe.get_all("Team", filters={"team_lead": user, "is_active": 1}, pluck="name") or [])
	member_rows = frappe.db.sql(
		"""
		select distinct t.name
		from `tabTeam User` tu
		inner join `tabTeam` t on t.name = tu.parent
		where tu.parenttype = 'Team'
		  and tu.user = %s
		  and ifnull(tu.is_active, 1) = 1
		  and ifnull(t.is_active, 1) = 1
		""",
		user,
		as_dict=True,
	)
	return led | {row.name for row in member_rows}


def is_effective_team_leader(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if is_privileged(user):
		return True
	return has_team_leader_role(user) and bool(managed_team_names(user))


def get_managed_team_users(user: str | None = None) -> list[str]:
	user = user or frappe.session.user
	teams = managed_team_names(user)
	if not teams:
		return []

	rows = frappe.db.sql(
		"""
		select distinct tu.user
		from `tabTeam User` tu
		inner join `tabTeam` t on t.name = tu.parent
		where tu.parenttype = 'Team'
		  and t.name in %(teams)s
		  and ifnull(tu.is_active, 1) = 1
		  and ifnull(t.is_active, 1) = 1
		  and tu.user is not null
		  and tu.user != ''
		""",
		{"teams": tuple(teams)},
		as_dict=True,
	)
	users = {row.user for row in rows}
	users.update(frappe.get_all("Team", filters={"name": ["in", list(teams)], "is_active": 1}, pluck="team_lead") or [])
	return sorted(user for user in users if user)


def ensure_can_manage_assignment() -> None:
	if is_privileged() or is_effective_team_leader():
		return
	frappe.throw("Only configured Team Leader users can assign or unassign CRM Lead records.", frappe.PermissionError)


def ensure_target_in_managed_team(new_owner: str) -> None:
	if is_privileged():
		return
	if new_owner not in set(get_managed_team_users()):
		frappe.throw("Team Leaders can assign only to active users in their managed teams.", frappe.PermissionError)


def ensure_can_manage_lead(lead: str) -> None:
	if is_privileged():
		return
	if not frappe.has_permission("CRM Lead", "write", lead):
		frappe.throw("You can manage only CRM Leads visible to your managed team.", frappe.PermissionError)


@lru_cache(maxsize=4096)
def _allowed_pipelines(user: str) -> frozenset[str]:
	from frappe.core.doctype.user_permission.user_permission import get_user_permissions

	config = get_config()
	if not config.pipeline_doctype:
		return frozenset()

	perms = get_user_permissions(user) or {}
	raw = perms.get(config.pipeline_doctype) or []
	values = set()
	for value in raw:
		if isinstance(value, str):
			values.add(value)
		elif isinstance(value, dict):
			values.add(value.get("doc") or value.get("value") or value.get("name"))
	values.discard("")
	values.discard(None)
	return frozenset(values)


def agent_allowed_for_pipeline(user: str, pipeline: str | None) -> bool:
	if not pipeline:
		return True
	config = get_config()
	if not config.pipeline_doctype:
		return True
	allowed = _allowed_pipelines(user)
	return bool(allowed and pipeline in allowed)

