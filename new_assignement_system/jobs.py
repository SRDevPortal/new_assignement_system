from __future__ import annotations

import frappe
from frappe.utils import add_to_date, cint, now_datetime

from new_assignement_system.engine.queue import due_queue_names, enqueue_queue_item, mark_retry, try_lock
from new_assignement_system.engine.service import auto_assign_lead, auto_unassign_lead
from new_assignement_system.settings import get_settings


def process_assignment_queue_item(queue_name: str) -> dict | None:
	row = try_lock(queue_name)
	if not row:
		return None

	try:
		if row.event_type == "Unassign":
			result = auto_unassign_lead(row.lead, event_type=row.event_type, queue=queue_name)
			status = "Cancelled" if result.get("status") == "ok" else "Skipped"
		else:
			result = auto_assign_lead(row.lead, event_type=row.event_type, queue=queue_name)
			status = "Assigned" if result.get("status") == "ok" else "Skipped"
		values = {
			"status": status,
			"error": None,
			"locked_by": None,
			"locked_at": None,
		}
		if _should_retry_capacity_skip(result):
			values.update(
				{
					"status": "Retry",
					"next_retry_at": add_to_date(now_datetime(), minutes=1),
					"error": str(result.get("reason") or "")[:1000],
				}
			)
		frappe.db.set_value(
			"New Assignement System Queue",
			queue_name,
			values,
			update_modified=True,
		)
		frappe.db.commit()
		return result
	except Exception:
		mark_retry(queue_name, frappe.get_traceback(), row.attempts)
		frappe.db.commit()
		return None


def _should_retry_capacity_skip(result: dict | None) -> bool:
	if not result or result.get("status") != "skipped":
		return False
	return "fresh lead limit" in str(result.get("reason") or "").lower()


def process_due_short_queue(limit: int | None = None) -> None:
	settings = get_settings()
	for queue_name in due_queue_names(limit):
		enqueue_queue_item(queue_name, queue=settings.default_queue)


def retry_failed_queue() -> None:
	frappe.db.sql(
		"""
		update `tabNew Assignement System Queue`
		set status = 'Retry',
			next_retry_at = %s
		where status = 'Failed'
		  and attempts < 5
		""",
		now_datetime(),
	)


def enqueue_unassigned_fresh_leads(limit: int | None = None) -> int:
	from new_assignement_system.engine.eligibility import get_fresh_lead_status
	from new_assignement_system.engine.queue import enqueue_lead
	from new_assignement_system.engine.service import can_auto_assign_lead

	settings = get_settings()
	if not settings.enabled or not cint(settings.enable_fresh_lead_limit):
		return 0

	fresh_status = get_fresh_lead_status(settings)
	if not fresh_status:
		return 0

	conditions = [
		"(lead_owner is null or lead_owner = '')",
		"status = %(fresh_status)s",
	]
	if frappe.db.has_column("CRM Lead", "converted"):
		conditions.append("ifnull(converted, 0) = 0")
	if frappe.db.has_column("CRM Lead", "sr_is_archived"):
		conditions.append("ifnull(sr_is_archived, 0) = 0")

	rows = frappe.db.sql(
		f"""
		select name
		from `tabCRM Lead`
		where {" and ".join(conditions)}
		order by creation asc
		limit %(limit)s
		""",
		{
			"fresh_status": fresh_status,
			"limit": int(limit or settings.queue_batch_size or 100),
		},
		as_dict=True,
	)

	queued = 0
	for row in rows:
		if not can_auto_assign_lead(row.name, event_type="Fresh FIFO"):
			continue
		if enqueue_lead(row.name, event_type="Fresh FIFO", priority=20, process_now=False):
			queued += 1
	return queued


def enqueue_stale_reassignment_candidates() -> None:
	from new_assignement_system.engine.queue import enqueue_lead
	from new_assignement_system.engine.service import can_auto_assign_lead

	settings = get_settings()
	if not settings.stale_reassignment_enabled:
		return

	cutoff = add_to_date(now_datetime(), minutes=-int(settings.stale_after_minutes or 120))
	filters = {
		"lead_owner": ["is", "set"],
		"modified": ["<=", cutoff],
	}
	if frappe.db.has_column("CRM Lead", "converted"):
		filters["converted"] = 0
	if frappe.db.has_column("CRM Lead", "sr_is_archived"):
		filters["sr_is_archived"] = 0

	leads = frappe.get_all(
		"CRM Lead",
		filters=filters,
		pluck="name",
		order_by="modified asc",
		limit_page_length=int(settings.queue_batch_size or 100),
	)
	for lead in leads:
		if not can_auto_assign_lead(lead, event_type="Stale"):
			continue
		enqueue_lead(lead, event_type="Stale", priority=50, process_now=False)


def repair_agent_state_sample() -> None:
	from new_assignement_system.engine.counters import sync_from_teams

	sync_from_teams()


def sync_agent_login_status() -> None:
	from new_assignement_system.engine.counters import sync_login_status

	sync_login_status()


def rebuild_agent_states() -> None:
	from new_assignement_system.engine.counters import rebuild_all

	rebuild_all()


def reset_daily_agent_counts() -> None:
	from new_assignement_system.engine.counters import reset_daily_counts

	reset_daily_counts()


def repair_assignment_helpers() -> None:
	from new_assignement_system.engine.sync import sync_assignment_helpers

	leads = frappe.get_all(
		"CRM Lead",
		filters={"lead_owner": ["is", "set"]},
		fields=["name", "lead_owner"],
		limit_page_length=int(get_settings().queue_batch_size or 100),
	)
	for lead in leads:
		sync_assignment_helpers(lead.name, lead.lead_owner)


def bulk_assign(leads: list[str], new_owner: str, reason: str | None = None) -> dict:
	from new_assignement_system.engine.service import assign_lead

	updated = 0
	for lead in leads:
		assign_lead(lead, new_owner, reason=reason or "Bulk assignment", triggered_by="Bulk", ignore_permissions=True)
		updated += 1
	frappe.db.commit()
	return {"status": "ok", "updated": updated}


def bulk_clear(leads: list[str], reason: str | None = None) -> dict:
	from new_assignement_system.engine.service import clear_lead_assignment

	updated = 0
	for lead in leads:
		clear_lead_assignment(lead, reason=reason or "Bulk clear", triggered_by="Bulk")
		updated += 1
	frappe.db.commit()
	return {"status": "ok", "updated": updated}
