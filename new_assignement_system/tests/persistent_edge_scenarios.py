from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from unittest.mock import patch

import frappe

from crm_lead_dedupe.leads.dup_hooks import _mark_doc_pending
from new_assignement_system.engine.context import get_lead_context
from new_assignement_system.integrations.dedupe import evaluate_assignment_readiness
from new_assignement_system.settings import get_settings


RUN_ID = "EDGE20-R1"
PIPELINE = "EDGE20 QA"
ALT_PIPELINE = "EDGE20 QA ALT"
BASE_MOBILE = 7612399000


SCENARIOS = {
	1: "valid_pending_30_seconds",
	2: "waiting_for_required_pipeline",
	3: "waiting_for_required_source",
	4: "unsafe_blocked_mobile",
	5: "short_mobile",
	6: "completed_primary",
	7: "completed_duplicate",
	8: "archived_duplicate",
	9: "converted_primary",
	10: "dedupe_failed",
	11: "dedupe_processing",
	12: "pending_allowed_by_configuration",
	13: "skipped_allowed_by_configuration",
	14: "completed_blank_result",
	15: "legacy_master_fallback",
	16: "legacy_duplicate_fallback",
	17: "duplicate_link_hard_block",
	18: "assigned_duplicate_review_required",
	19: "waiting_for_agent_after_primary",
	20: "pipeline_change_requeues_dedupe",
}


def _settings(**overrides):
	settings = frappe._dict(get_settings().copy())
	settings.update(
		{
			"enable_dedupe_readiness_check": 1,
			"dedupe_required_stage": "Completed",
			"dedupe_allowed_results": "Primary",
			"dedupe_missing_field_behavior": "Proceed",
		}
	)
	settings.update(overrides)
	return settings


def _ensure_pipeline(name: str) -> None:
	if frappe.db.exists("SR Lead Pipeline", name):
		return
	doc = frappe.new_doc("SR Lead Pipeline")
	doc.sr_pipeline_name = name
	doc.insert(ignore_permissions=True)
	frappe.db.commit()


@contextmanager
def _isolated_insert_hooks():
	old_assignment = getattr(frappe.flags, "new_assignement_system_disable_hooks", False)
	old_dedupe = getattr(frappe.flags, "crm_lead_dedupe_scheduler", False)
	frappe.flags.new_assignement_system_disable_hooks = True
	frappe.flags.crm_lead_dedupe_scheduler = True
	try:
		yield
	finally:
		frappe.flags.new_assignement_system_disable_hooks = old_assignment
		frappe.flags.crm_lead_dedupe_scheduler = old_dedupe


def _lead_label(number: int) -> str:
	return f"{RUN_ID}-S{number:02d}-{SCENARIOS[number]}"


def _mobile(number: int) -> str:
	return str(BASE_MOBILE + number)


def _create_lead(number: int, *, mobile: str | None = None, pipeline: str | None = PIPELINE):
	label = _lead_label(number)
	existing = frappe.db.get_value("CRM Lead", {"lead_name": label}, "name")
	if existing:
		return frappe.get_doc("CRM Lead", existing), False

	_ensure_pipeline(PIPELINE)
	_ensure_pipeline(ALT_PIPELINE)
	doc = frappe.new_doc("CRM Lead")
	doc.first_name = label
	doc.lead_name = label
	doc.status = "Fresh"
	doc.mobile_no = mobile if mobile is not None else _mobile(number)
	doc.sr_lead_pipeline = pipeline
	doc.sr_lead_platform = "Website"
	with _isolated_insert_hooks():
		doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc, True


def _state_values(doc) -> dict:
	fields = [
		"sr_dedupe_pending",
		"sr_dedupe_status",
		"sr_dedupe_stage",
		"sr_dedupe_result",
		"sr_dedupe_pipeline",
		"sr_dedupe_queued_at",
		"sr_dedupe_not_before",
		"sr_dedupe_started_at",
		"sr_dedupe_completed_at",
		"sr_dedupe_input_hash",
		"sr_dedupe_error",
	]
	return {field: doc.get(field) for field in fields if frappe.db.has_column("CRM Lead", field)}


def _queue_using_live_delay(doc, *, require_pipeline=False, require_source=False) -> None:
	def test_setting(key):
		if key == "crm_lead_dedupe_delay_seconds":
			return 30
		if key == "crm_lead_dedupe_require_pipeline":
			return 1 if require_pipeline else 0
		if key == "crm_lead_dedupe_require_source":
			return 1 if require_source else 0
		return 0

	with patch("crm_lead_dedupe.leads.dup_hooks.get_setting", side_effect=test_setting):
		_mark_doc_pending(doc, force=True)
	frappe.db.set_value("CRM Lead", doc.name, _state_values(doc), update_modified=False)
	frappe.db.commit()


def _set(lead: str, **values) -> None:
	values = {key: value for key, value in values.items() if frappe.db.has_column("CRM Lead", key)}
	frappe.db.set_value("CRM Lead", lead, values, update_modified=False)
	frappe.db.commit()


def _evaluate(lead: str, **setting_overrides):
	row = get_lead_context(lead)
	return evaluate_assignment_readiness(row, _settings(**setting_overrides))


def _result(number: int, lead: str, created: bool, expected, actual, extra=None):
	passed = actual == expected
	row = frappe.db.get_value(
		"CRM Lead",
		lead,
		[
			"name",
			"lead_name",
			"mobile_no",
			"sr_mobile_norm",
			"sr_lead_pipeline",
			"lead_owner",
			"converted",
			"sr_is_archived",
			"sr_is_duplicate",
			"sr_duplicate_of_name",
			"sr_dedupe_status",
			"sr_dedupe_stage",
			"sr_dedupe_result",
			"sr_dedupe_queued_at",
			"sr_dedupe_not_before",
			"sr_assignment_stage",
		],
		as_dict=True,
	)
	return {
		"scenario": number,
		"action": SCENARIOS[number],
		"status": "PASS" if passed else "FAIL",
		"created": created,
		"lead": lead,
		"expected": expected,
		"actual": actual,
		"lead_state": row,
		"extra": extra or {},
	}


def run_action(number: int):
	number = int(number)
	if number not in SCENARIOS:
		frappe.throw(f"Unknown EDGE20 scenario: {number}")
	if int(frappe.db.get_single_value("CRM Lead Dedupe Settings", "crm_lead_dedupe_delay_seconds") or 0) != 30:
		frappe.throw("CRM Lead Dedupe delay must be 30 seconds for EDGE20 tests.")

	if number == 1:
		doc, created = _create_lead(number)
		_queue_using_live_delay(doc)
		row = frappe.db.get_value("CRM Lead", doc.name, ["sr_dedupe_stage", "sr_dedupe_queued_at", "sr_dedupe_not_before"], as_dict=True)
		delay = int((row.sr_dedupe_not_before - row.sr_dedupe_queued_at).total_seconds())
		actual = (row.sr_dedupe_stage, delay, _evaluate(doc.name)[0])
		return _result(number, doc.name, created, ("Pending", 30, False), actual)

	if number == 2:
		doc, created = _create_lead(number)
		frappe.db.set_value("CRM Lead", doc.name, "sr_lead_pipeline", None, update_modified=False)
		frappe.db.commit()
		doc = frappe.get_doc("CRM Lead", doc.name)
		_queue_using_live_delay(doc, require_pipeline=True)
		actual = (frappe.db.get_value("CRM Lead", doc.name, "sr_dedupe_stage"), _evaluate(doc.name)[0])
		return _result(number, doc.name, created, ("Waiting for Metadata", False), actual)

	if number == 3:
		doc, created = _create_lead(number)
		doc.source = None
		_queue_using_live_delay(doc, require_source=True)
		actual = (frappe.db.get_value("CRM Lead", doc.name, "sr_dedupe_stage"), _evaluate(doc.name)[0])
		return _result(number, doc.name, created, ("Waiting for Metadata", False), actual)

	if number == 4:
		doc, created = _create_lead(number, mobile="0000000000")
		_queue_using_live_delay(doc)
		actual = (*frappe.db.get_value("CRM Lead", doc.name, ["sr_dedupe_stage", "sr_dedupe_result"]), _evaluate(doc.name)[0])
		return _result(number, doc.name, created, ("Completed", "Skipped", False), actual)

	if number == 5:
		doc, created = _create_lead(number, mobile="12345")
		_queue_using_live_delay(doc)
		actual = (*frappe.db.get_value("CRM Lead", doc.name, ["sr_dedupe_stage", "sr_dedupe_result"]), _evaluate(doc.name)[0])
		return _result(number, doc.name, created, ("Completed", "Skipped", False), actual)

	if number == 6:
		doc, created = _create_lead(number)
		_set(doc.name, sr_dedupe_pending=0, sr_dedupe_status="Master", sr_dedupe_stage="Completed", sr_dedupe_result="Primary")
		return _result(number, doc.name, created, (True, False, None), _evaluate(doc.name))

	if number == 7:
		primary = frappe.db.get_value("CRM Lead", {"lead_name": _lead_label(6)}, "name")
		if not primary:
			frappe.throw("Run scenario 6 before scenario 7.")
		doc, created = _create_lead(number, mobile=_mobile(6))
		_set(doc.name, sr_dedupe_pending=0, sr_dedupe_status="Duplicate", sr_dedupe_stage="Completed", sr_dedupe_result="Duplicate", sr_is_duplicate=1, sr_duplicate_of_name=primary)
		return _result(number, doc.name, created, (False, True, "Lead is marked duplicate"), _evaluate(doc.name), {"primary": primary})

	if number == 8:
		primary = frappe.db.get_value("CRM Lead", {"lead_name": _lead_label(6)}, "name")
		doc, created = _create_lead(number)
		_set(doc.name, sr_dedupe_stage="Completed", sr_dedupe_result="Duplicate", sr_is_archived=1, sr_is_duplicate=1, sr_duplicate_of_name=primary)
		return _result(number, doc.name, created, (False, True, "Lead is archived"), _evaluate(doc.name), {"primary": primary})

	if number == 9:
		doc, created = _create_lead(number)
		_set(doc.name, converted=1, sr_dedupe_stage="Completed", sr_dedupe_result="Primary")
		return _result(number, doc.name, created, (False, True, "Lead is converted"), _evaluate(doc.name))

	if number == 10:
		doc, created = _create_lead(number)
		_set(doc.name, sr_dedupe_status="Failed", sr_dedupe_stage="Failed", sr_dedupe_result=None, sr_dedupe_error="EDGE20 simulated failure")
		return _result(number, doc.name, created, (False, False, "Dedupe failed"), _evaluate(doc.name))

	if number == 11:
		doc, created = _create_lead(number)
		_set(doc.name, sr_dedupe_status="Processing", sr_dedupe_stage="Processing", sr_dedupe_result=None)
		return _result(number, doc.name, created, (False, False, "Waiting for dedupe stage Completed"), _evaluate(doc.name))

	if number == 12:
		doc, created = _create_lead(number)
		_set(doc.name, sr_dedupe_status="Pending", sr_dedupe_stage="Pending", sr_dedupe_result=None)
		actual = _evaluate(doc.name, dedupe_required_stage="Pending")
		return _result(number, doc.name, created, (True, False, None), actual)

	if number == 13:
		doc, created = _create_lead(number)
		_set(doc.name, sr_dedupe_status="Skipped", sr_dedupe_stage="Completed", sr_dedupe_result="Skipped")
		actual = _evaluate(doc.name, dedupe_allowed_results="Primary\nSkipped")
		return _result(number, doc.name, created, (True, False, None), actual)

	if number == 14:
		doc, created = _create_lead(number)
		_set(doc.name, sr_dedupe_status=None, sr_dedupe_stage="Completed", sr_dedupe_result=None)
		return _result(number, doc.name, created, (False, False, "Dedupe result blank is not allowed"), _evaluate(doc.name))

	if number == 15:
		doc, created = _create_lead(number)
		_set(doc.name, sr_dedupe_status="Master", sr_dedupe_stage=None, sr_dedupe_result=None)
		return _result(number, doc.name, created, (True, False, None), _evaluate(doc.name))

	if number == 16:
		doc, created = _create_lead(number)
		_set(doc.name, sr_dedupe_status="Duplicate", sr_dedupe_stage=None, sr_dedupe_result=None)
		return _result(number, doc.name, created, (False, True, "Dedupe result is Duplicate"), _evaluate(doc.name))

	if number == 17:
		primary = frappe.db.get_value("CRM Lead", {"lead_name": _lead_label(6)}, "name")
		doc, created = _create_lead(number)
		_set(doc.name, sr_dedupe_status="Master", sr_dedupe_stage="Completed", sr_dedupe_result="Primary", sr_duplicate_of_name=primary)
		return _result(number, doc.name, created, (False, True, "Lead points to a duplicate primary"), _evaluate(doc.name), {"primary": primary})

	if number == 18:
		primary = frappe.db.get_value("CRM Lead", {"lead_name": _lead_label(6)}, "name")
		doc, created = _create_lead(number)
		_set(doc.name, lead_owner="Administrator", sr_dedupe_stage="Completed", sr_dedupe_result="Duplicate", sr_is_duplicate=1, sr_duplicate_of_name=primary, sr_assignment_stage="Review Required", sr_assignment_reason="EDGE20 owner preserved")
		row = frappe.db.get_value("CRM Lead", doc.name, ["lead_owner", "sr_assignment_stage"], as_dict=True)
		return _result(number, doc.name, created, ("Administrator", "Review Required"), (row.lead_owner, row.sr_assignment_stage), {"primary": primary})

	if number == 19:
		doc, created = _create_lead(number)
		_set(doc.name, sr_dedupe_stage="Completed", sr_dedupe_result="Primary", sr_assignment_stage="Waiting for Agent", sr_assignment_reason="EDGE20 no agent available")
		actual = (frappe.db.get_value("CRM Lead", doc.name, "sr_assignment_stage"), _evaluate(doc.name)[0])
		return _result(number, doc.name, created, ("Waiting for Agent", True), actual)

	if number == 20:
		doc, created = _create_lead(number)
		old_hash = sha256(f"{doc.sr_mobile_norm}|{PIPELINE}|".encode()).hexdigest()
		_set(doc.name, sr_dedupe_pending=0, sr_dedupe_status="Master", sr_dedupe_stage="Completed", sr_dedupe_result="Primary", sr_dedupe_input_hash=old_hash, sr_dedupe_pipeline=PIPELINE)
		doc = frappe.get_doc("CRM Lead", doc.name)
		doc.sr_lead_pipeline = ALT_PIPELINE
		with patch("crm_lead_dedupe.leads.dup_hooks.get_setting", side_effect=lambda key: 30 if key == "crm_lead_dedupe_delay_seconds" else 0):
			with _isolated_assignment_only():
				doc.save(ignore_permissions=True)
		frappe.db.commit()
		row = frappe.db.get_value("CRM Lead", doc.name, ["sr_dedupe_stage", "sr_dedupe_pipeline", "sr_dedupe_queued_at", "sr_dedupe_not_before"], as_dict=True)
		delay = int((row.sr_dedupe_not_before - row.sr_dedupe_queued_at).total_seconds())
		actual = (row.sr_dedupe_stage, row.sr_dedupe_pipeline, delay, _evaluate(doc.name)[0])
		return _result(number, doc.name, created, ("Pending", ALT_PIPELINE, 30, False), actual)


@contextmanager
def _isolated_assignment_only():
	old_assignment = getattr(frappe.flags, "new_assignement_system_disable_hooks", False)
	frappe.flags.new_assignement_system_disable_hooks = True
	try:
		yield
	finally:
		frappe.flags.new_assignement_system_disable_hooks = old_assignment


def run_s01(): return run_action(1)
def run_s02(): return run_action(2)
def run_s03(): return run_action(3)
def run_s04(): return run_action(4)
def run_s05(): return run_action(5)
def run_s06(): return run_action(6)
def run_s07(): return run_action(7)
def run_s08(): return run_action(8)
def run_s09(): return run_action(9)
def run_s10(): return run_action(10)
def run_s11(): return run_action(11)
def run_s12(): return run_action(12)
def run_s13(): return run_action(13)
def run_s14(): return run_action(14)
def run_s15(): return run_action(15)
def run_s16(): return run_action(16)
def run_s17(): return run_action(17)
def run_s18(): return run_action(18)
def run_s19(): return run_action(19)
def run_s20(): return run_action(20)
