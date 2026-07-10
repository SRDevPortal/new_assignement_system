from __future__ import annotations

import frappe
from frappe.model.document import Document

from new_assignement_system.integrations.team import get_active_team_members


class NewAssignementSystemRule(Document):
	def validate(self) -> None:
		if self.priority is None:
			self.priority = 100
		if not self.strategy:
			self.strategy = "Balanced Load"
		if not self.filter_match_mode:
			self.filter_match_mode = "Match All Configured Filters"
		self.validate_assign_to_users()
		self.validate_reassignment_values()
		self.validate_metadata_filters("metadata_filters")
		self.validate_metadata_filters("unassign_metadata_filters")
		if self.metadata_filters_json:
			try:
				frappe.parse_json(self.metadata_filters_json)
			except Exception:
				frappe.throw("Metadata Filters JSON must be valid JSON.")
		if self.unassign_condition:
			try:
				compile(self.unassign_condition, "<crm_lead_unassign_condition>", "eval")
			except SyntaxError as exc:
				frappe.throw(f"Unassign Condition must be a valid Python expression: {exc}")

	def validate_assign_to_users(self) -> None:
		seen = set()
		duplicates = set()
		team_members = set()
		if self.get("team"):
			if not frappe.db.exists("DocType", "Team"):
				frappe.throw("Team DocType is required to use Team-based assignment.")
			if not frappe.db.exists("Team", {"name": self.team, "is_active": 1}):
				frappe.throw(f"Team {self.team} must be active.")
			team_members = set(get_active_team_members(self.team))
		for row in self.get("assign_to_users", []):
			if not row.user:
				continue
			if row.user in seen:
				duplicates.add(row.user)
			if team_members and row.user not in team_members:
				frappe.throw(
					frappe._("User {0} is not an active member of Team {1}.").format(row.user, self.team)
				)
			seen.add(row.user)
		if duplicates:
			frappe.throw("Duplicate users in Assign To Users: " + ", ".join(sorted(duplicates)))

	def validate_metadata_filters(self, fieldname: str) -> None:
		for row in self.get(fieldname, []):
			if not row.enabled:
				continue
			if not row.fieldname:
				frappe.throw("Metadata filter fieldname is required.")
			if not row.operator:
				row.operator = "Equals"

	def validate_reassignment_values(self) -> None:
		for row in self.get("reassignment_new_values", []):
			if not row.enabled or not row.lead_owner:
				continue
			if not frappe.db.exists("User", {"name": row.lead_owner, "enabled": 1}):
				frappe.throw(f"Reassignment target user is invalid or disabled: {row.lead_owner}")
