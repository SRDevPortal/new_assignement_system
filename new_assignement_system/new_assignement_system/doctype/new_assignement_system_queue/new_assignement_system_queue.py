from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class NewAssignementSystemQueue(Document):
	def before_insert(self) -> None:
		if not self.status:
			self.status = "Pending"
		if self.attempts is None:
			self.attempts = 0
		if not self.next_retry_at:
			self.next_retry_at = now_datetime()
		if not self.priority:
			self.priority = 100

	def validate(self) -> None:
		if self.metadata_snapshot:
			try:
				frappe.parse_json(self.metadata_snapshot)
			except Exception:
				frappe.throw("Metadata Snapshot must be valid JSON.")

