from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha1

import frappe
from frappe.utils import cint

from new_assignement_system.engine.audit import log_assignment
from new_assignement_system.engine.context import get_lead_context, snapshot_json
from new_assignement_system.engine.lead_state import set_assignment_state
from new_assignement_system.engine.counters import decrement_agent, increment_agent
from new_assignement_system.engine.eligibility import (
	agent_has_fresh_lead_capacity,
	get_candidate_agents,
	get_agent_fresh_lead_count,
	get_fresh_lead_status,
	is_fresh_lead,
	is_user_session_available,
)
from new_assignement_system.engine.rules import match_rule, match_unassign_rule
from new_assignement_system.engine.strategies import select_agent
from new_assignement_system.engine.sync import clear_assignment_helpers, sync_assignment_helpers
from new_assignement_system.integrations.dedupe import evaluate_assignment_readiness
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
	lead_updates: dict | None = None,
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
	allowed, _terminal, readiness_reason = evaluate_assignment_readiness(row, settings)
	if not allowed:
		return _skip(lead, readiness_reason, triggered_by or "Direct", queue, row=row, rule=frappe._dict(name=rule))

	if (
		old_owner != new_owner
		and cint(settings.enable_fresh_lead_limit)
		and is_fresh_lead(row, settings=settings)
	):
		with _fresh_capacity_lock(new_owner):
			row = get_lead_context(lead, for_update=True)
			old_owner = row.get("lead_owner")
			fresh_lead_count = get_agent_fresh_lead_count(
				new_owner,
				get_fresh_lead_status(settings),
				for_update=True,
			)
			if old_owner != new_owner and not agent_has_fresh_lead_capacity(
				new_owner,
				row,
				settings=settings,
				fresh_lead_count=fresh_lead_count,
			):
				log_assignment(
					lead=lead,
					action="Skipped",
					old_owner=old_owner,
					new_owner=new_owner,
					rule=rule,
					strategy=strategy,
					queue=queue,
					triggered_by=triggered_by,
					reason="Fresh lead limit reached for owner",
					metadata_snapshot=snapshot_json(row),
				)
				set_assignment_state(
					lead,
					"Capacity Hold",
					reason="Fresh lead limit reached for owner",
					retry_seconds=int(settings.assignment_readiness_retry_seconds or 60),
				)
				return {"status": "skipped", "reason": "fresh_lead_limit_reached", "owner": new_owner}
			result = _assign_lead_unchecked(
				lead,
				new_owner,
				row=row,
				old_owner=old_owner,
				settings=settings,
				reason=reason,
				rule=rule,
				strategy=strategy,
				queue=queue,
				source=source,
				pipeline=pipeline,
				lead_updates=lead_updates,
				triggered_by=triggered_by,
			)
			frappe.db.commit()
			return result

	if old_owner == new_owner:
		apply_lead_updates(lead, source=source, pipeline=pipeline, lead_updates=lead_updates)
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
		set_assignment_state(lead, "Assigned", reason=reason or "Lead already assigned", rule=rule)
		return {"status": "skipped", "reason": "already_assigned", "owner": new_owner}

	return _assign_lead_unchecked(
		lead,
		new_owner,
		row=row,
		old_owner=old_owner,
		settings=settings,
		reason=reason,
		rule=rule,
		strategy=strategy,
		queue=queue,
		source=source,
		pipeline=pipeline,
		lead_updates=lead_updates,
		triggered_by=triggered_by,
	)


def _assign_lead_unchecked(
	lead: str,
	new_owner: str,
	*,
	row: frappe._dict,
	old_owner: str | None,
	settings: frappe._dict,
	reason: str | None = None,
	rule: str | None = None,
	strategy: str | None = None,
	queue: str | None = None,
	source: str | None = None,
	pipeline: str | None = None,
	lead_updates: dict | None = None,
	triggered_by: str | None = None,
) -> dict:
	frappe.flags.new_assignement_system_in_progress = True
	try:
		values = {"lead_owner": new_owner}
		if cint(settings.sync_team_from_lead_owner) and has_team_field():
			values["team"] = get_team_for_user(new_owner)
		values.update(get_lead_update_values(source=source, pipeline=pipeline, lead_updates=lead_updates))
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
	set_assignment_state(
		lead,
		"Assigned",
		reason=reason or action,
		rule=rule,
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
	set_assignment_state(lead, "Cancelled", reason=reason or "Assignment cleared")
	return {"status": "ok", "action": "Unassigned", "old_owner": old_owner}


def reassign_lead(lead: str, new_owner: str, **kwargs) -> dict:
	return assign_lead(lead, new_owner, **kwargs)


def apply_lead_updates(
	lead: str,
	*,
	source: str | None = None,
	pipeline: str | None = None,
	lead_updates: dict | None = None,
) -> None:
	values = get_lead_update_values(source=source, pipeline=pipeline, lead_updates=lead_updates)
	if values:
		frappe.db.set_value("CRM Lead", lead, values)


def get_lead_update_values(
	*,
	source: str | None = None,
	pipeline: str | None = None,
	lead_updates: dict | None = None,
) -> dict:
	values = {}
	if source:
		values["source"] = source
	if pipeline:
		values["sr_lead_pipeline"] = pipeline
	for fieldname, value in (lead_updates or {}).items():
		if fieldname == "lead_owner" or value in (None, ""):
			continue
		values[fieldname] = value
	return {fieldname: value for fieldname, value in values.items() if frappe.db.has_column("CRM Lead", fieldname)}


def auto_assign_lead(lead: str, *, event_type: str = "Manual", queue: str | None = None) -> dict:
	settings = get_settings()
	if not settings.enabled:
		return _skip(lead, "Assignment app disabled", event_type, queue)

	row = get_lead_context(lead, for_update=True)
	allowed, _terminal, reason = evaluate_assignment_readiness(row, settings)
	if not allowed:
		return _skip(lead, reason, event_type, queue, row=row)
	set_assignment_state(lead, "Processing", reason=f"Evaluating {event_type} assignment", increment_attempts=True)

	rule = match_rule(row, event_type=event_type)
	if not rule:
		if settings.fallback_user:
			if not _fallback_allowed(settings.fallback_user, settings, row):
				return _skip(
					lead,
					"No rule matched; fallback user is not eligible",
					event_type,
					queue,
					row=row,
				)
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
			allowed, _terminal, reason = evaluate_assignment_readiness(row, settings)
			if not allowed:
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
	reassignment_values = dict(rule.get("reassignment_target_values") or {})
	target_owner = reassignment_values.pop("lead_owner", None)

	if target_owner:
		return assign_lead(
			lead,
			target_owner,
			reason=f"Auto reassignment by rule {rule.name}",
			rule=rule.name,
			strategy=strategy,
			queue=queue,
			source=rule.target_source,
			pipeline=rule.get("target_pipeline"),
			lead_updates=reassignment_values,
			triggered_by=event_type,
			ignore_permissions=True,
		)

	candidates = get_candidate_agents(rule, row)
	selected = select_agent(candidates, strategy, row, rule=rule)
	if not selected:
		if cint(settings.enable_fresh_lead_limit) and is_fresh_lead(row, settings=settings):
			return _skip(
				lead,
				f"No active agent below fresh lead limit for rule {rule.name}",
				event_type,
				queue,
				row=row,
				rule=rule,
			)
		fallback = rule.fallback_user or settings.fallback_user
		if fallback:
			if not _fallback_allowed(fallback, settings, row):
				return _skip(
					lead,
					f"No available online agent for rule {rule.name}; fallback user is not eligible",
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
				lead_updates=reassignment_values,
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
		lead_updates=reassignment_values,
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


@contextmanager
def _fresh_capacity_lock(agent: str):
	lock_name = "nas_fresh_" + sha1(str(agent).encode("utf-8")).hexdigest()
	acquired = frappe.db.sql("select get_lock(%s, %s)", (lock_name, 30))[0][0]
	if not acquired:
		frappe.throw(f"Could not acquire Fresh Lead Capacity lock for {agent}")
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
	allowed, _terminal, _reason = evaluate_assignment_readiness(row, settings)
	if not allowed:
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


def _fallback_allowed(user: str, settings: frappe._dict, row: dict | None = None) -> bool:
	if not is_user_session_available(user):
		return False
	return agent_has_fresh_lead_capacity(user, row, settings=settings)


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
	reason_text = str(reason or "")
	if "duplicate" in reason_text.lower() or "archived" in reason_text.lower():
		stage = "Skipped Duplicate"
	elif "dedupe" in reason_text.lower() or "metadata" in reason_text.lower():
		stage = "Waiting for Dedupe"
	elif "fresh lead limit" in reason_text.lower() or "capacity" in reason_text.lower():
		stage = "Capacity Hold"
	elif "no assignment rule" in reason_text.lower() or "no rule matched" in reason_text.lower():
		stage = "No Matching Rule"
	elif "no eligible agent" in reason_text.lower() or "no available online agent" in reason_text.lower():
		stage = "Waiting for Agent"
	else:
		stage = "Failed"
	settings = get_settings()
	retry = None
	if stage in {"Waiting for Dedupe", "Waiting for Agent", "Capacity Hold"}:
		retry = int(settings.assignment_readiness_retry_seconds or 60)
	set_assignment_state(
		lead,
		stage,
		reason=reason,
		rule=(rule or {}).get("name"),
		increment_attempts=True,
		retry_seconds=retry,
	)
	return {"status": "skipped", "reason": reason}
