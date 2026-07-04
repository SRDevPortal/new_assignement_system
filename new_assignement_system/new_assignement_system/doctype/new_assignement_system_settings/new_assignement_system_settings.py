from __future__ import annotations

import frappe
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
		if self.enable_fresh_slot_auto_refill is None:
			self.enable_fresh_slot_auto_refill = 1
		if not self.get("fresh_slot_auto_refill_mode"):
			self.fresh_slot_auto_refill_mode = "Status Change Only"
		if not self.fresh_lead_status:
			self.fresh_lead_status = "New"
		if not self.fresh_lead_limit_per_agent:
			self.fresh_lead_limit_per_agent = 5
		if self.auto_unassign_on_update is None:
			self.auto_unassign_on_update = 0
		if self.enable_status_based_assignment is None:
			self.enable_status_based_assignment = 0
		self.validate_status_assignment_users()

	def validate_status_assignment_users(self) -> None:
		seen_statuses = set()
		for row in self.get("status_assignment_users") or []:
			if not row.enabled:
				continue
			if not row.lead_status or not row.assign_to_user:
				frappe.throw("Lead Status and Assign To User are required in enabled status assignment rows.")
			if row.lead_status in seen_statuses:
				frappe.throw(f"Duplicate status assignment mapping for {row.lead_status}.")
			seen_statuses.add(row.lead_status)
			if not frappe.db.exists("User", {"name": row.assign_to_user, "enabled": 1}):
				frappe.throw(f"Invalid or disabled status assignment user: {row.assign_to_user}")
