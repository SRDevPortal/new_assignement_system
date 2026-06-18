from __future__ import annotations

import frappe
from frappe.model.document import Document


class NewAssignementSystemAgentState(Document):
	def autoname(self) -> None:
		self.name = self.agent

	def validate(self) -> None:
		if not self.agent:
			frappe.throw("Agent is required.")
		if self.weight is None or self.weight <= 0:
			self.weight = 1
		if self.capacity is None:
			self.capacity = 0
		if self.current_open_leads is None:
			self.current_open_leads = 0
		self.load_score = self.get_load_score()

	def get_load_score(self) -> float:
		capacity = self.capacity or 0
		if capacity <= 0:
			return float(self.current_open_leads or 0) / float(self.weight or 1)
		return float(self.current_open_leads or 0) / float(capacity * (self.weight or 1))
