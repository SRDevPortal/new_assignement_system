from __future__ import annotations

import frappe

from new_assignement_system.integrations.role_permissions import (
	get_managed_team_users,
	has_agent_role,
	has_team_leader_role,
	is_effective_team_leader,
	is_privileged,
)
from new_assignement_system.settings import get_settings


@frappe.whitelist()
def get_new_assignement_system_context() -> dict:
	user = frappe.session.user
	settings = get_settings()
	return {
		"user": user,
		"enabled": bool(settings.enabled),
		"disable_manual_assign_to": bool(settings.disable_manual_assign_to),
		"inline_assign_on_insert": bool(settings.inline_assign_on_insert),
		"override_api_owner_when_rule_matches": bool(settings.override_api_owner_when_rule_matches),
		"can_manage_assignment": is_privileged(user) or is_effective_team_leader(user),
		"is_privileged": is_privileged(user),
		"has_team_leader_role": has_team_leader_role(user),
		"has_agent_role": has_agent_role(user),
		"managed_team_users": get_managed_team_users(user),
	}
