from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha1

import frappe
from frappe.utils import cint

from new_assignement_system.engine.audit import log_assignment
from new_assignement_system.engine.context import get_lead_context, snapshot_json
from new_assignement_system.engine.counters import decrement_agent, increment_agent
from new_assignement_system.engine.eligibility import get_candidate_agents, is_user_session_available
from new_assignement_system.engine.rules import match_rule, match_unassign_rule
from new_assignement_system.engine.strategies import select_agent
from new_assignement_system.engine.sync import clear_assignment_helpers, sync_assignment_helpers
from new_assignement_system.integrations.dedupe import should_skip_lead
from new_assignement_system.integrations.team import get_team_for_user, has_team_field
from new_assignement_system.settings import get_settings


def assign_lead(
	lead: str,
	new_owner: str,
	*,
	reason: str | None = None,
	rule: str | None = None,
	strategy: str | None = None,
	queue: str | None = None,
	source: str | None = None,
	pipeline: str | None = None,
	triggered_by: str | None = None,
	ignore_permissions: bool = False,
) -> dict:
	if not new_owner:
		frappe.throw("New owner is required.")
	if not frappe.db.exists("User", {"name": new_owner, "enabled": 1}):
		frappe.throw(f"Invalid or disabled user: {new_owner}")

	settings = get_settings()
	row = get_lead_context(lead, for_update=True)
	old_owner = row.get("lead_owner")

	if old_owner == new_owner:
		if cint(settings.sync_team_from_lead_owner) and has_team_field():
			frappe.db.set_value("CRM Lead", lead, "team", get_team_for_user(new_owner), update_modified=False)
		sync_assignment_helpers(lead, new_owner, description="Lead Owner")
		log_assignment(
			lead=lead,
			action="Skipped",
			old_owner=old_owner,
			new_owner=new_owner,
			rule=rule,
			strategy=strategy,
			queue=queue,
			triggered_by=triggered_by,
			reason=reason or "Lead already assigned to this owner",
			metadata_snapshot=snapshot_json(row),
		)
		return {"status": "skipped", "reason": "already_assigned", "owner": new_owner}

	frappe.flags.new_assignement_system_in_progress = True
	try:
		values = {"lead_owner": new_owner}
		if cint(settings.sync_team_from_lead_owner) and has_team_field():
			values["team"] = get_team_for_user(new_owner)
		if source:
			values["source"] = source
		if pipeline and frappe.db.has_column("CRM Lead", "sr_lead_pipeline"):
			values["sr_lead_pipeline"] = pipeline
		frappe.db.set_value("CRM Lead", lead, values)
		if old_owner:
			decrement_agent(old_owner)
		increment_agent(new_owner, reassigned=bool(old_owner))
		sync_assignment_helpers(lead, new_owner, description="Lead Owner")
	finally:
		frappe.flags.new_assignement_system_in_progress = False

	action = "Reassigned" if old_owner else "Assigned"
	log_assignment(
		lead=lead,
		action=action,
		old_owner=old_owner,
		new_owner=new_owner,
		rule=rule,
		strategy=strategy,
		queue=queue,
		triggered_by=triggered_by,
		reason=reason,
		metadata_snapshot=snapshot_json(row),
	)
	return {"status": "ok", "action": action, "old_owner": old_owner, "new_owner": new_owner}


def clear_lead_assignment(
	lead: str,
	*,
	reason: str | None = None,
	queue: str | None = None,
	triggered_by: str | None = None,
) -> dict:
	row = get_lead_context(lead)
	old_owner = row.get("lead_owner")

	frappe.flags.new_assignement_system_clear_in_progress = True
	try:
		values = {"lead_owner": None}
		if cint(get_settings().sync_team_from_lead_owner) and has_team_field():
			values["team"] = None
		frappe.db.set_value("CRM Lead", lead, values)
		decrement_agent(old_owner)
		clear_assignment_helpers(lead)
	finally:
		frappe.flags.new_assignement_system_clear_in_progress = False

	log_assignment(
		lead=lead,
		action="Unassigned",
		old_owner=old_owner,
		queue=queue,
		triggered_by=triggered_by,
		reason=reason,
		metadata_snapshot=snapshot_json(row),
	)
	return {"status": "ok", "action": "Unassigned", "old_owner": old_owner}


def reassign_lead(lead: str, new_owner: str, **kwargs) -> dict:
	return assign_lead(lead, new_owner, **kwargs)


def auto_assign_lead(lead: str, *, event_type: str = "Manual", queue: str | None = None) -> dict:
	settings = get_settings()
	if not settings.enabled:
		return _skip(lead, "Assignment app disabled", event_type, queue)

	row = get_lead_context(lead, for_update=True)
	skip, reason = should_skip_lead(row)
	if skip:
		return _skip(lead, reason, event_type, queue, row=row)

	rule = match_rule(row, event_type=event_type)
	if not rule:
		if settings.fallback_user:
			if not _fallback_allowed(settings.fallback_user, settings):
				return _skip(lead, "No rule matched; fallback user has no active session", event_type, queue, row=row)
			return assign_lead(
				lead,
				settings.fallback_user,
				reason="No rule matched; fallback user selected",
				strategy=settings.default_strategy,
				queue=queue,
				triggered_by=event_type,
				ignore_permissions=True,
			)
		return _skip(lead, "No assignment rule matched", event_type, queue, row=row)

	strategy = rule.strategy or settings.default_strategy
	if strategy == "Round Robin":
		with _round_robin_lock(rule.name):
			row = get_lead_context(lead, for_update=True)
			skip, reason = should_skip_lead(row)
			if skip:
				return _skip(lead, reason, event_type, queue, row=row, rule=rule)
			result = _assign_by_rule(lead, row, rule, strategy, event_type, queue, settings)
			frappe.db.commit()
			return result

	return _assign_by_rule(lead, row, rule, strategy, event_type, queue, settings)


def _assign_by_rule(
	lead: str,
	row: frappe._dict,
	rule: frappe._dict,
	strategy: str,
	event_type: str,
	queue: str | None,
	settings: frappe._dict,
) -> dict:
	candidates = get_candidate_agents(rule, row)
	selected = select_agent(candidates, strategy, row, rule=rule)
	if not selected:
		fallback = rule.fallback_user or settings.fallback_user
		if fallback:
			if not _fallback_allowed(fallback, settings):
				return _skip(
					lead,
					f"No available online agent for rule {rule.name}; fallback user has no active session",
					event_type,
					queue,
					row=row,
					rule=rule,
				)
			return assign_lead(
				lead,
				fallback,
				reason=f"No available online agent for rule {rule.name}; fallback user selected",
				rule=rule.name,
				strategy=strategy,
				queue=queue,
				source=rule.target_source,
				pipeline=rule.get("target_pipeline"),
				triggered_by=event_type,
				ignore_permissions=True,
			)
		return _skip(lead, f"No eligible agent for rule {rule.name}", event_type, queue, row=row, rule=rule)

	return assign_lead(
		lead,
		selected.agent,
		reason=f"Auto assignment by rule {rule.name}",
		rule=rule.name,
		strategy=strategy,
		queue=queue,
		source=rule.target_source,
		pipeline=rule.get("target_pipeline"),
		triggered_by=event_type,
		ignore_permissions=True,
	)


@contextmanager
def _round_robin_lock(rule: str):
	lock_name = "nas_rr_" + sha1(str(rule).encode("utf-8")).hexdigest()
	acquired = frappe.db.sql("select get_lock(%s, %s)", (lock_name, 30))[0][0]
	if not acquired:
		frappe.throw(f"Could not acquire Round Robin lock for rule {rule}")
	try:
		yield
	finally:
		frappe.db.sql("select release_lock(%s)", (lock_name,))


def auto_unassign_lead(lead: str, *, event_type: str = "Update", queue: str | None = None) -> dict:
	settings = get_settings()
	if not settings.enabled:
		return _skip(lead, "Assignment app disabled", event_type, queue)

	row = get_lead_context(lead, for_update=True)
	if not row.get("lead_owner"):
		return _skip(lead, "Lead is already unassigned", event_type, queue, row=row)

	rule = match_unassign_rule(row, event_type=event_type)
	if not rule:
		return _skip(lead, "No unassign rule matched", event_type, queue, row=row)

	return clear_lead_assignment(
		lead,
		reason=f"Auto unassignment by rule {rule.name}",
		queue=queue,
		triggered_by=event_type,
	)


def can_auto_assign_lead(lead: str, *, event_type: str = "Manual") -> bool:
	settings = get_settings()
	if not settings.enabled:
		return False

	row = get_lead_context(lead)
	skip, _reason = should_skip_lead(row)
	if skip:
		return False

	return bool(match_rule(row, event_type=event_type) or settings.fallback_user)


def can_auto_unassign_lead(lead: str, *, event_type: str = "Update") -> bool:
	settings = get_settings()
	if not settings.enabled:
		return False

	row = get_lead_context(lead)
	if not row.get("lead_owner"):
		return False
	return bool(match_unassign_rule(row, event_type=event_type))


def _fallback_allowed(user: str, settings: frappe._dict) -> bool:
	if cint(settings.allow_fallback_without_active_session):
		return True
	return is_user_session_available(user)


def _skip(
	lead: str,
	reason: str | None,
	event_type: str,
	queue: str | None,
	*,
	row: dict | None = None,
	rule: frappe._dict | None = None,
) -> dict:
	row = row or get_lead_context(lead)
	log_assignment(
		lead=lead,
		action="Skipped",
		old_owner=row.get("lead_owner"),
		rule=(rule or {}).get("name"),
		strategy=(rule or {}).get("strategy"),
		queue=queue,
		triggered_by=event_type,
		reason=reason,
		metadata_snapshot=snapshot_json(row),
	)
	return {"status": "skipped", "reason": reason}
