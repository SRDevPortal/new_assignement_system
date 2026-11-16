from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import frappe
from frappe.utils import add_to_date, now_datetime

from new_assignement_system.engine.context import get_lead_context, snapshot_hash, snapshot_json
from new_assignement_system.engine.lead_state import set_assignment_state
from new_assignement_system.number_privacy import sanitize_for_storage
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
		enqueue_after_commit=True,
		job_id="nas-item-" + sha256(queue_name.encode()).hexdigest(),
		deduplicate=True,
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


def mark_retry(queue_name: str, error: str, attempts: int, *, claim=None, busy=False) -> None:
	if claim is not None:
		# The failed transaction has already been rolled back by the caller.
		# Reacquire NOWAIT and refuse to overwrite a competing/newer claimant.
		rows = frappe.db.sql(
			"""select status, attempts, locked_by from `tabNew Assignement System Queue`
			where name=%s for update nowait""", (queue_name,), as_dict=True,
		)
		if not rows:
			return
		current = rows[0]
		if current.status == "Processing":
			if current.locked_by != claim.locked_by:
				return
		elif current.status not in {"Pending", "Retry"} or int(current.attempts or 0) != attempts - 1:
			return
		# Some assignment services commit business state before the queue row.
		# A retry must not repeat an already committed assignment/unassignment.
		action = frappe.db.get_value(
			"New Assignement System Log",
			{"lead": claim.lead, "queue": queue_name, "status": "Success",
			 "action": ["in", ["Assigned", "Reassigned", "Unassigned"]]},
			"action", order_by="creation desc",
		)
		if action:
			frappe.db.set_value(QUEUE_DOCTYPE, queue_name, {
				"status": "Cancelled" if action == "Unassigned" else "Assigned",
				"error": None, "locked_by": None, "locked_at": None,
			}, update_modified=True)
			return
	if busy:
		attempts = max(0, attempts - 1)
	status = "Failed" if attempts >= 5 else "Retry"
	if busy:
		status = "Retry"
	next_retry_at = add_to_date(now_datetime(), seconds=60 if busy else 60 * min(30, max(1, attempts * 2)))
	frappe.db.set_value(
		QUEUE_DOCTYPE,
		queue_name,
		{
			"status": status,
			"attempts": attempts,
			"error": sanitize_for_storage(error)[:1000],
			"next_retry_at": next_retry_at,
			"locked_by": None,
			"locked_at": None,
		},
		update_modified=True,
	)


def try_lock(queue_name: str) -> frappe._dict | None:
	# Called at the background job transaction boundary. NOWAIT prevents a
	# duplicate job occupying a worker while another claimant holds this row.
	waits_column = "capacity_waits" if frappe.db.has_column(QUEUE_DOCTYPE, "capacity_waits") else "0 as capacity_waits"
	rows = frappe.db.sql(
		f"""select name, lead, event_type, status, attempts, {waits_column},
		          next_retry_at from `tabNew Assignement System Queue`
		where name=%s for update nowait""",
		(queue_name,), as_dict=True,
	)
	row = rows[0] if rows else None
	if not row or row.status not in {"Pending", "Retry"}:
		return None
	if row.get("next_retry_at") and frappe.utils.get_datetime(row.next_retry_at) > now_datetime():
		return None

	frappe.db.set_value(
		QUEUE_DOCTYPE,
		queue_name,
		{
			"status": "Processing",
			"attempts": int(row.attempts or 0) + 1,
			"locked_by": (token := uuid4().hex),
			"locked_at": now_datetime(),
		},
		update_modified=True,
	)
	row.attempts = int(row.attempts or 0) + 1
	row.locked_by = token
	return frappe._dict(row)


def capacity_delay(queue_name: str, waits: int) -> int:
	"""Bounded exponential fallback with stable per-item jitter (seconds)."""
	base = min(900, 60 * (2 ** min(4, max(0, int(waits) - 1))))
	return base + int(sha256(queue_name.encode()).hexdigest()[:4], 16) % 31


def recover_abandoned_claims(limit=20) -> None:
	"""Recover claims older than three 300s job timeouts, never a live RQ job."""
	from frappe.utils.background_jobs import is_job_enqueued
	cutoff = add_to_date(now_datetime(), seconds=-900)
	for name in frappe.get_all(QUEUE_DOCTYPE,
		filters={"status": "Processing", "locked_at": ["<", cutoff]},
		pluck="name", order_by="locked_at asc", limit_page_length=limit):
		if is_job_enqueued("nas-item-" + sha256(name.encode()).hexdigest()):
			continue
		try:
			rows = frappe.db.sql(
				"""select name, lead, locked_by, attempts from `tabNew Assignement System Queue`
				where name=%s and status='Processing' and locked_at < %s
				for update nowait""", (name, cutoff), as_dict=True)
			if rows:
				row = rows[0]
				mark_retry(name, "Recovered abandoned assignment claim", int(row.attempts or 0), claim=row)
			frappe.db.commit()
		except (frappe.QueryTimeoutError, frappe.QueryDeadlockError):
			frappe.db.rollback()
