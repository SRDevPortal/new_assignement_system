from __future__ import annotations

import frappe
from frappe.utils import add_to_date, now_datetime

from new_assignement_system.engine.context import get_lead_context, snapshot_hash, snapshot_json
from new_assignement_system.engine.lead_state import set_assignment_state
from new_assignement_system.settings import get_settings

QUEUE_DOCTYPE = "New Assignement System Queue"


def enqueue_lead(
	lead: str,
	*,
	event_type: str = "Insert",
	priority: int = 100,
	rule: str | None = None,
	process_now: bool = True,
) -> str | None:
	if not frappe.db.exists("DocType", QUEUE_DOCTYPE):
		return None
	if not frappe.db.exists("CRM Lead", lead):
		return None

	existing = frappe.db.get_value(
		QUEUE_DOCTYPE,
		{
			"lead": lead,
			"status": ["in", ["Pending", "Processing", "Retry"]],
		},
		"name",
		order_by="creation asc",
	)
	if existing:
		return existing

	row = get_lead_context(lead)
	doc = frappe.get_doc(
		{
			"doctype": QUEUE_DOCTYPE,
			"lead": lead,
			"event_type": event_type,
			"status": "Pending",
			"priority": priority,
			"rule": rule,
			"next_retry_at": now_datetime(),
			"metadata_hash": snapshot_hash(row),
			"metadata_snapshot": snapshot_json(row),
		}
	)
	doc.insert(ignore_permissions=True)
	set_assignment_state(lead, "Queued", reason=f"Queued for {event_type} assignment")

	if process_now and get_settings().queue_enabled:
		enqueue_queue_item(doc.name)
	return doc.name


def enqueue_queue_item(queue_name: str, *, queue: str | None = None) -> None:
	settings = get_settings()
	frappe.enqueue(
		"new_assignement_system.jobs.process_assignment_queue_item",
		queue=queue or settings.default_queue,
		timeout=300,
		queue_name=queue_name,
	)


def due_queue_names(limit: int | None = None) -> list[str]:
	settings = get_settings()
	return frappe.get_all(
		QUEUE_DOCTYPE,
		filters={
			"status": ["in", ["Pending", "Retry"]],
			"next_retry_at": ["<=", now_datetime()],
		},
		pluck="name",
		order_by="priority asc, creation asc",
		limit_page_length=limit or int(settings.queue_batch_size or 100),
	)


def mark_retry(queue_name: str, error: str, attempts: int) -> None:
	status = "Failed" if attempts >= 5 else "Retry"
	next_retry_at = add_to_date(now_datetime(), minutes=min(30, max(1, attempts * 2)))
	frappe.db.set_value(
		QUEUE_DOCTYPE,
		queue_name,
		{
			"status": status,
			"error": error[:1000],
			"next_retry_at": next_retry_at,
			"locked_by": None,
			"locked_at": None,
		},
		update_modified=True,
	)


def try_lock(queue_name: str) -> frappe._dict | None:
	row = frappe.db.get_value(
		QUEUE_DOCTYPE,
		queue_name,
		["name", "lead", "event_type", "status", "attempts"],
		as_dict=True,
	)
	if not row or row.status not in {"Pending", "Retry"}:
		return None

	frappe.db.set_value(
		QUEUE_DOCTYPE,
		queue_name,
		{
			"status": "Processing",
			"attempts": int(row.attempts or 0) + 1,
			"locked_by": frappe.local.site or frappe.session.user,
			"locked_at": now_datetime(),
		},
		update_modified=True,
	)
	row.attempts = int(row.attempts or 0) + 1
	return frappe._dict(row)
