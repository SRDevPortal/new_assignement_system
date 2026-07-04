from __future__ import annotations

import frappe
from frappe.utils import cint

from new_assignement_system.engine.eligibility import would_exceed_fresh_lead_limit
from new_assignement_system.engine.queue import enqueue_lead
from new_assignement_system.engine.rules import match_rule
from new_assignement_system.engine.service import (
	assign_lead,
	auto_assign_lead,
	auto_unassign_lead,
	can_auto_unassign_lead,
)
from new_assignement_system.engine.sync import sync_assignment_helpers
from new_assignement_system.integrations.dedupe import should_skip_lead
from new_assignement_system.settings import (
	FRESH_SLOT_REFILL_TRIGGER_STATUS_CHANGE,
	get_settings,
	get_status_assignment_user,
	should_run_fresh_slot_auto_refill,
)

WATCH_FIELDS = {
	"status",
	"source",
	"sr_lead_pipeline",
	"sr_lead_disposition",
	"disposition",
	"campaign",
	"utm_campaign",
	"sr_campaign",
	"sr_utm_campaign",
	"sr_utm_campaign_id",
	"sr_f_campaign_id",
	"sr_f_campaign_name",
	"sr_w_campaign_name",
	"sr_w_source_id",
	"lead_score",
	"lead_temperature",
}


def before_validate(doc, method: str | None = None) -> None:
	if getattr(frappe.flags, "new_assignement_system_disable_hooks", False):
		return

	settings = get_settings()
	if not settings.enabled:
		return

	if doc.is_new() and doc.get("lead_owner") and _should_override_api_owner(doc, settings):
		doc.set("lead_owner", None)

	_validate_direct_fresh_capacity_change(doc, settings)


def after_insert(doc, method: str | None = None) -> None:
	if getattr(frappe.flags, "new_assignement_system_disable_hooks", False):
		return

	settings = get_settings()
	if not settings.enabled:
		return

	if doc.get("lead_owner"):
		sync_assignment_helpers(doc.name, doc.get("lead_owner"))
		return

	if settings.auto_assign_on_insert:
		if cint(settings.inline_assign_on_insert) or not cint(settings.queue_enabled):
			frappe.db.after_commit.add(lambda lead=doc.name: _assign_insert_inline_or_queue(lead))
			return
		enqueue_lead(doc.name, event_type="Insert", process_now=True)


def on_update(doc, method: str | None = None) -> None:
	if getattr(frappe.flags, "new_assignement_system_disable_hooks", False):
		return

	settings = get_settings()
	if not settings.enabled or getattr(frappe.flags, "new_assignement_system_in_progress", False):
		return

	if _fresh_slot_opened(doc, settings):
		agent = (doc.get_doc_before_save() or {}).get("lead_owner")
		frappe.db.after_commit.add(lambda agent=agent: _enqueue_fresh_refill_for_agent(agent))

	if doc.has_value_changed("lead_owner"):
		sync_assignment_helpers(doc.name, doc.get("lead_owner"))
		return

	if _assign_by_status_change(doc):
		return

	if any(_has_changed(doc, fieldname) for fieldname in WATCH_FIELDS):
		if cint(settings.auto_unassign_on_update) and can_auto_unassign_lead(doc.name, event_type="Update"):
			_process_update_inline_or_queue(doc.name, event_type="Unassign")
			return

		# A lead may land before WA/channel mapping writes pipeline or source id.
		# If owner is blank, let the normal assignment service try again when
		# watched routing fields become ready. Existing owners are only changed
		# when explicit reassignment is enabled.
		if doc.get("lead_owner") and not cint(settings.auto_reassign_on_update):
			return
		if not doc.get("lead_owner") and not cint(settings.auto_assign_on_insert):
			return
		_process_update_inline_or_queue(doc.name, event_type="Update")


def _has_changed(doc, fieldname: str) -> bool:
	return hasattr(doc, fieldname) and doc.has_value_changed(fieldname)


def _validate_direct_fresh_capacity_change(doc, settings) -> None:
	if not cint(settings.enable_fresh_lead_limit):
		return

	owner = doc.get("lead_owner")
	if not owner:
		return

	fresh_status = str(settings.fresh_lead_status or "New").strip()
	if not fresh_status or doc.get("status") != fresh_status:
		return

	if not doc.is_new() and not (_has_changed(doc, "status") or _has_changed(doc, "lead_owner")):
		return

	row = frappe._dict(doc.as_dict())
	if not would_exceed_fresh_lead_limit(owner, row, settings=settings):
		return

	frappe.throw(
		frappe._("Cannot save this fresh lead for {0} because the user already has {1} fresh leads.").format(
			owner,
			settings.fresh_lead_limit_per_agent,
		),
		title=frappe._("Fresh Lead Limit Reached"),
	)


def _assign_by_status_change(doc) -> bool:
	if not _has_changed(doc, "status"):
		return False

	target_user = get_status_assignment_user(doc.get("status"))
	if not target_user:
		return False

	try:
		assign_lead(
			doc.name,
			target_user,
			reason=f"Status changed to {doc.get('status')}",
			triggered_by="Status Based Assignment",
			ignore_permissions=True,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "New Assignement System Status Assignment Failed")
		raise
	return True


def _fresh_slot_opened(doc, settings) -> bool:
	if (
		not cint(settings.enable_fresh_lead_limit)
		or not should_run_fresh_slot_auto_refill(FRESH_SLOT_REFILL_TRIGGER_STATUS_CHANGE, settings)
		or not _has_changed(doc, "status")
	):
		return False

	before = doc.get_doc_before_save()
	if not before:
		return False

	fresh_status = str(settings.fresh_lead_status or "New").strip()
	return bool(fresh_status and before.get("status") == fresh_status and doc.get("status") != fresh_status)


def _enqueue_fresh_refill_for_agent(agent: str | None = None) -> None:
	from new_assignement_system.jobs import enqueue_fresh_refill_for_agent

	try:
		if agent:
			enqueue_fresh_refill_for_agent(agent)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "New Assignement System Fresh FIFO Failed")


def _should_override_api_owner(doc, settings) -> bool:
	if not settings.auto_assign_on_insert or not settings.override_api_owner_when_rule_matches:
		return False

	row = frappe._dict(doc.as_dict())
	skip, _reason = should_skip_lead(row)
	if skip:
		return False

	row.lead_owner = None
	return bool(match_rule(row, event_type="Insert"))


def _assign_insert_inline_or_queue(lead: str) -> None:
	if not frappe.db.exists("CRM Lead", lead):
		return
	try:
		auto_assign_lead(lead, event_type="Insert")
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Inline New Assignement System Failed")
		enqueue_lead(lead, event_type="Insert", process_now=True)
		frappe.db.commit()


def _process_update_inline_or_queue(lead: str, *, event_type: str) -> None:
	settings = get_settings()
	if cint(settings.queue_enabled):
		enqueue_lead(lead, event_type=event_type, process_now=True)
		return

	frappe.db.after_commit.add(lambda lead=lead, event_type=event_type: _process_update_inline(lead, event_type))


def _process_update_inline(lead: str, event_type: str) -> None:
	if not frappe.db.exists("CRM Lead", lead):
		return
	try:
		if event_type == "Unassign":
			auto_unassign_lead(lead, event_type="Update")
		else:
			auto_assign_lead(lead, event_type=event_type)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Inline New Assignement System Update Failed")
		enqueue_lead(lead, event_type=event_type, process_now=True)
		frappe.db.commit()
