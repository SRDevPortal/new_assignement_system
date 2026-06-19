from __future__ import annotations

import frappe
from frappe.utils import cint

from new_assignement_system.engine.queue import enqueue_lead
from new_assignement_system.engine.rules import match_rule
from new_assignement_system.engine.service import (
	auto_assign_lead,
	auto_unassign_lead,
	can_auto_unassign_lead,
)
from new_assignement_system.engine.sync import sync_assignment_helpers
from new_assignement_system.integrations.dedupe import should_skip_lead
from new_assignement_system.settings import get_settings

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
	if not settings.enabled or not doc.is_new():
		return

	if doc.get("lead_owner") and _should_override_api_owner(doc, settings):
		doc.set("lead_owner", None)


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

	if doc.has_value_changed("lead_owner"):
		sync_assignment_helpers(doc.name, doc.get("lead_owner"))
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
