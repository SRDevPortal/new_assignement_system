from __future__ import annotations

from frappe.model.document import Document


class NewAssignementSystemSettings(Document):
	def validate(self) -> None:
		if not self.default_queue:
			self.default_queue = "lead_assignment_short"
		if not self.bulk_queue:
			self.bulk_queue = "lead_assignment_bulk"
		if not self.scheduler_queue:
			self.scheduler_queue = "lead_assignment_scheduler"
		if not self.bulk_inline_limit:
			self.bulk_inline_limit = 20
		if not self.queue_batch_size:
			self.queue_batch_size = 100
		if self.enable_total_capacity_limit is None:
			self.enable_total_capacity_limit = 1
		if self.enable_fresh_lead_limit is None:
			self.enable_fresh_lead_limit = 0
		if not self.fresh_lead_status:
			self.fresh_lead_status = "New"
		if not self.fresh_lead_limit_per_agent:
			self.fresh_lead_limit_per_agent = 5
		if self.auto_unassign_on_update is None:
			self.auto_unassign_on_update = 0
