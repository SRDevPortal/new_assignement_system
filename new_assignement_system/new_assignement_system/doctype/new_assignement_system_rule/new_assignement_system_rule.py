from __future__ import annotations

import frappe
from frappe.model.document import Document


class NewAssignementSystemRule(Document):
	def validate(self) -> None:
		if self.priority is None:
			self.priority = 100
		if not self.strategy:
			self.strategy = "Balanced Load"
		self.validate_assign_to_users()
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
		for row in self.get("assign_to_users", []):
			if not row.user:
				continue
			if row.user in seen:
				duplicates.add(row.user)
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
