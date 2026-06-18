from __future__ import annotations

import frappe
from frappe.model.document import Document


class NewAssignementSystemLog(Document):
	def validate(self) -> None:
		if self.metadata_snapshot:
			try:
				frappe.parse_json(self.metadata_snapshot)
			except Exception:
				frappe.throw("Metadata Snapshot must be valid JSON.")

