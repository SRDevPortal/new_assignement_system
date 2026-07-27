from __future__ import annotations

import frappe
from frappe.utils import cint


DEDUPE_READY_STATUSES = {"Master", "Completed", "Skipped"}
DEDUPE_BLOCKED_STATUSES = {"Pending", "Processing", "Failed"}


def _has_lead_column(fieldname: str) -> bool:
	try:
		return bool(frappe.db.has_column("CRM Lead", fieldname))
	except Exception:
		return False


def is_dedupe_ready(row: dict) -> bool:
	"""Return whether a lead is safe for assignment after dedupe."""
	if _has_lead_column("sr_dedupe_pending") and cint(row.get("sr_dedupe_pending")):
		return False

	if not _has_lead_column("sr_dedupe_status"):
		return True

	status = str(row.get("sr_dedupe_status") or "").strip()
	if status in DEDUPE_BLOCKED_STATUSES:
		return False
	if status in DEDUPE_READY_STATUSES:
		return True

	# A normalized mobile with no result has not been scanned yet. Leads without
	# a dedupe key remain assignable for backward compatibility.
	if _has_lead_column("sr_mobile_norm") and row.get("sr_mobile_norm"):
		return False
	return True


def dedupe_ready_sql_conditions(table_alias: str | None = None) -> list[str]:
	"""Index-friendly SQL predicates shared by Fresh FIFO/count queries."""
	prefix = f"`{table_alias}`." if table_alias else ""
	conditions = []
	if _has_lead_column("sr_is_archived"):
		conditions.append(f"{prefix}sr_is_archived = 0")
	if _has_lead_column("sr_is_duplicate"):
		conditions.append(f"{prefix}sr_is_duplicate = 0")
	if _has_lead_column("sr_dedupe_pending"):
		conditions.append(f"{prefix}sr_dedupe_pending = 0")
	if _has_lead_column("sr_dedupe_status"):
		conditions.append(f"{prefix}sr_dedupe_status in ('Master', 'Completed', 'Skipped')")
	return conditions


def should_skip_lead(row: dict) -> tuple[bool, str | None]:
	if cint(row.get("converted")):
		return True, "Lead is converted"
	if cint(row.get("sr_is_archived")):
		return True, "Lead is archived"
	if cint(row.get("sr_is_duplicate")):
		return True, "Lead is marked duplicate"
	if row.get("sr_duplicate_of_name") or row.get("sr_duplicate_of"):
		return True, "Lead points to a duplicate primary"
	if not is_dedupe_ready(row):
		return True, "Lead is waiting for dedupe"
	return False, None


def reconcile_after_dedupe(
	canonical_lead: str,
	merged_leads: list[str] | None = None,
	affected_agents: list[str] | None = None,
) -> dict:
	"""Reconcile assignment helpers/slots after merge-to-new commits."""
	from new_assignement_system.engine.context import get_lead_context
	from new_assignement_system.engine.counters import reconcile_agent_open_lead_count
	from new_assignement_system.engine.eligibility import is_fresh_lead
	from new_assignement_system.engine.queue import enqueue_lead
	from new_assignement_system.engine.sync import sync_assignment_helpers
	from new_assignement_system.jobs import enqueue_fresh_refill_for_agent
	from new_assignement_system.settings import get_settings

	if not canonical_lead or not frappe.db.exists("CRM Lead", canonical_lead):
		return {"status": "skipped", "reason": "canonical_lead_missing"}

	row = get_lead_context(
		canonical_lead,
		extra=["sr_dedupe_pending", "sr_dedupe_status", "sr_mobile_norm"],
	)
	owner = row.get("lead_owner")
	agents = {agent for agent in (affected_agents or []) if agent}
	if owner:
		agents.add(owner)

	skip, reason = should_skip_lead(row)
	if skip:
		for agent in agents:
			reconcile_agent_open_lead_count(agent)
		frappe.db.commit()
		return {
			"status": "skipped",
			"reason": reason,
			"affected_agents": sorted(agents),
		}

	if owner:
		sync_assignment_helpers(canonical_lead, owner, description="Lead Owner preserved after dedupe")

	for agent in agents:
		reconcile_agent_open_lead_count(agent)

	queued = None
	settings = get_settings()
	if settings.enabled and is_fresh_lead(row, settings=settings) and not owner:
		queued = enqueue_lead(
			canonical_lead,
			event_type="Fresh FIFO",
			priority=20,
			process_now=False,
		)

	for agent in agents:
		enqueue_fresh_refill_for_agent(agent)

	frappe.db.commit()
	return {
		"status": "ok",
		"canonical_lead": canonical_lead,
		"merged_leads": merged_leads or [],
		"owner": owner,
		"queued": queued,
		"affected_agents": sorted(agents),
	}
