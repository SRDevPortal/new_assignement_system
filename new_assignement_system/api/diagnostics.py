from __future__ import annotations

import frappe

from new_assignement_system.engine.service import auto_assign_lead, clear_lead_assignment


RULE_CASES = (
	("120251580552780012", "aman_mi@sriaas.com"),
	("120250583333020012", "karan_drh@sriaas.com"),
	("120250723559390012", "mandeep_mi@sriaas.com"),
	("120250583820420012", "ankitchaudhary_mi@sriaas.com"),
)


def delete_mock_crm_leads() -> dict:
	leads = frappe.get_all(
		"CRM Lead",
		filters={"first_name": ["like", "CLA Mock%"]},
		pluck="name",
		limit_page_length=0,
	)

	for lead in leads:
		if frappe.db.get_value("CRM Lead", lead, "lead_owner"):
			clear_lead_assignment(lead, reason="Mock test cleanup", triggered_by="Mock Cleanup")
		_delete_crm_notifications_for_lead(lead)
		frappe.db.delete("ToDo", {"reference_type": "CRM Lead", "reference_name": lead})
		frappe.db.delete("DocShare", {"share_doctype": "CRM Lead", "share_name": lead})
		frappe.db.delete("New Assignement System Queue", {"lead": lead})
		frappe.db.delete("New Assignement System Log", {"lead": lead})
		frappe.delete_doc("CRM Lead", lead, force=True, ignore_permissions=True)

	frappe.db.commit()
	return {"deleted": len(leads), "leads": leads}


def delete_crm_leads_by_name_prefix(prefix: str) -> dict:
	if not prefix or len(prefix.strip()) < 8:
		frappe.throw("A specific CRM Lead name prefix of at least 8 characters is required.")

	prefix = prefix.strip()
	leads = frappe.get_all(
		"CRM Lead",
		filters={"name": ["like", f"{prefix}%"]},
		pluck="name",
		limit_page_length=0,
	)

	for lead in leads:
		if frappe.db.get_value("CRM Lead", lead, "lead_owner"):
			clear_lead_assignment(lead, reason="Prefix cleanup", triggered_by="Diagnostic Cleanup")
		_delete_crm_notifications_for_lead(lead)
		frappe.db.delete("ToDo", {"reference_type": "CRM Lead", "reference_name": lead})
		frappe.db.delete("DocShare", {"share_doctype": "CRM Lead", "share_name": lead})
		frappe.db.delete("New Assignement System Queue", {"lead": lead})
		frappe.db.delete("New Assignement System Log", {"lead": lead})
		frappe.delete_doc("CRM Lead", lead, force=True, ignore_permissions=True)

	frappe.db.commit()
	return {"prefix": prefix, "deleted": len(leads), "leads": leads}


def delete_srd_diag_aman_crm_leads() -> dict:
	return delete_crm_leads_by_name_prefix("SR-DIAG-AMAN-")


def delete_srd_diag_aman_any_crm_leads() -> dict:
	return delete_crm_leads_by_name_prefix("SR-DIAG-AMAN")


def delete_srd_diag_verify_aman_crm_leads() -> dict:
	return delete_crm_leads_by_name_prefix("SR-DIAG-VERIFY-AMAN-")


def delete_srd_diag_fixed_aman_crm_leads() -> dict:
	return delete_crm_leads_by_name_prefix("SR-DIAG-FIXED-AMAN-")


def delete_srd_diag_live_aman_crm_leads() -> dict:
	return delete_crm_leads_by_name_prefix("SR-DIAG-LIVE-AMAN-")


def delete_stale_mock_crm_notifications() -> dict:
	if not frappe.db.exists("DocType", "CRM Notification"):
		return {"deleted": 0, "notifications": []}

	notifications = frappe.get_all(
		"CRM Notification",
		filters={"notification_text": ["like", "%CLA Mock%"]},
		pluck="name",
		limit_page_length=0,
	)
	if frappe.db.exists("CRM Notification", "g7kh13jfbh") and "g7kh13jfbh" not in notifications:
		notifications.append("g7kh13jfbh")

	for notification in notifications:
		frappe.delete_doc("CRM Notification", notification, force=True, ignore_permissions=True)

	frappe.db.commit()
	return {"deleted": len(notifications), "notifications": notifications}


def inspect_reported_assignment_artifacts() -> dict:
	return inspect_assignment_artifacts(log_name="cdrsg4mrhu", queue_name="btdqdb6p50")


def inspect_reported_crm_notification() -> dict:
	return inspect_crm_notification("g7kh13jfbh")


def inspect_pankaj_non_matching_payload() -> dict:
	lead = frappe.db.get_value("CRM Lead", {"mobile_no": "9308727739"}, "name", order_by="creation desc")
	lead = lead or frappe.db.get_value("CRM Lead", {"email": "aksks88@gmail.com"}, "name", order_by="creation desc")
	lead = lead or ("CRM-LEAD-2026-01078" if frappe.db.exists("CRM Lead", "CRM-LEAD-2026-01078") else None)
	if not lead:
		return {"lead": None}
	return {
		"lead": _get_lead_snapshot(lead),
		"assignment_queue_count": frappe.db.count("New Assignement System Queue", {"lead": lead}),
		"assignment_log_count": frappe.db.count("New Assignement System Log", {"lead": lead}),
		"todo_count": frappe.db.count(
			"ToDo",
			{"reference_type": "CRM Lead", "reference_name": lead},
		),
		"open_todo_count": frappe.db.count(
			"ToDo",
			{"reference_type": "CRM Lead", "reference_name": lead, "status": "Open"},
		),
		"docshare_count": frappe.db.count(
			"DocShare",
			{"share_doctype": "CRM Lead", "share_name": lead},
		),
		"crm_notification_count": frappe.db.count(
			"CRM Notification",
			{"reference_doctype": "CRM Lead", "reference_name": lead},
		),
	}


def inspect_crm_lead_2026_01081() -> dict:
	return inspect_crm_lead("CRM-LEAD-2026-01081")


def inspect_crm_lead_2026_01082() -> dict:
	return inspect_crm_lead("CRM-LEAD-2026-01082")


def inspect_reported_01084_to_01087() -> dict:
	leads = [
		"CRM-LEAD-2026-01084",
		"CRM-LEAD-2026-01085",
		"CRM-LEAD-2026-01086",
		"CRM-LEAD-2026-01087",
	]
	logs = ["fgn9qgdb0n", "ethpacbrse", "e94mnaphle", "ag4enfpcub"]
	return {
		"leads": {lead: inspect_crm_lead(lead) for lead in leads},
		"logs": {
			log: frappe.db.get_value(
				"New Assignement System Log",
				log,
				[
					"name",
					"lead",
					"action",
					"status",
					"old_owner",
					"new_owner",
					"rule",
					"strategy",
					"queue",
					"triggered_by",
					"reason",
					"creation",
				],
				as_dict=True,
			)
			if frappe.db.exists("New Assignement System Log", log)
			else None
			for log in logs
		},
	}


def repair_reported_01084_to_01087_notifications_and_reasons() -> dict:
	from new_assignement_system.engine.sync import sync_crm_notification

	log_reason_by_name = {
		"fgn9qgdb0n": "Auto assignment by rule MI Lead Rule-Aman",
		"ethpacbrse": "Auto assignment by rule Mi Lead Rule-karan",
		"e94mnaphle": "Auto assignment by rule Mi Lead Rule-mandeep",
		"ag4enfpcub": "Auto assignment by rule Mi Lead Rule-ankit",
	}
	notification_leads = [
		"CRM-LEAD-2026-01084",
		"CRM-LEAD-2026-01085",
		"CRM-LEAD-2026-01086",
		"CRM-LEAD-2026-01087",
	]
	updated_logs = []
	notifications_before = {}
	notifications_after = {}

	for log_name, reason in log_reason_by_name.items():
		if frappe.db.exists("New Assignement System Log", log_name):
			frappe.db.set_value("New Assignement System Log", log_name, "reason", reason, update_modified=False)
			updated_logs.append(log_name)

	for lead in notification_leads:
		notifications_before[lead] = frappe.db.count(
			"CRM Notification",
			{"reference_doctype": "CRM Lead", "reference_name": lead},
		)
		owner = frappe.db.get_value("CRM Lead", lead, "lead_owner")
		if owner:
			sync_crm_notification(lead, owner)
		notifications_after[lead] = frappe.db.count(
			"CRM Notification",
			{"reference_doctype": "CRM Lead", "reference_name": lead},
		)

	frappe.db.commit()
	return {
		"updated_logs": updated_logs,
		"notifications_before": notifications_before,
		"notifications_after": notifications_after,
	}


def inspect_crm_lead(name: str) -> dict:
	if not frappe.db.exists("CRM Lead", name):
		return {"exists": False, "lead": name}

	return {
		"exists": True,
		"lead": _get_lead_snapshot(name),
		"assignment_queue": frappe.get_all(
			"New Assignement System Queue",
			filters={"lead": name},
			fields=["name", "status", "event_type", "attempts", "rule", "error", "creation", "modified"],
			order_by="creation desc",
			limit_page_length=20,
		),
		"assignment_log": frappe.get_all(
			"New Assignement System Log",
			filters={"lead": name},
			fields=["name", "action", "status", "old_owner", "new_owner", "rule", "reason", "creation"],
			order_by="creation desc",
			limit_page_length=20,
		),
		"todos": frappe.get_all(
			"ToDo",
			filters={"reference_type": "CRM Lead", "reference_name": name},
			fields=["name", "allocated_to", "status", "owner", "description", "assignment_rule", "creation"],
			order_by="creation desc",
			limit_page_length=20,
		),
		"docshares": frappe.get_all(
			"DocShare",
			filters={"share_doctype": "CRM Lead", "share_name": name},
			fields=["name", "user", "read", "write", "share", "creation"],
			order_by="creation desc",
			limit_page_length=20,
		),
		"crm_notifications": frappe.get_all(
			"CRM Notification",
			filters={"reference_doctype": "CRM Lead", "reference_name": name},
			fields=["name", "type", "from_user", "to_user", "message", "creation"],
			order_by="creation desc",
			limit_page_length=20,
		),
	}


def inspect_standard_assignment_rules_for_crm_lead() -> dict:
	if not frappe.db.exists("DocType", "Assignment Rule"):
		return {"assignment_rules": []}

	rules = frappe.get_all(
		"Assignment Rule",
		filters={"document_type": "CRM Lead", "disabled": 0},
		fields=["name", "rule", "assign_condition", "unassign_condition", "description", "modified"],
		order_by="modified desc",
		limit_page_length=50,
	)
	for rule in rules:
		rule["users"] = frappe.get_all(
			"Assignment Rule User",
			filters={"parent": rule.name},
			fields=["user"],
			order_by="idx asc",
			limit_page_length=100,
		)
	return {"assignment_rules": rules}


def inspect_new_assignement_system_rules() -> dict:
	if not frappe.db.exists("DocType", "New Assignement System Rule"):
		return {"rules": []}

	return {
		"rules": frappe.get_all(
			"New Assignement System Rule",
			fields=[
				"name",
				"rule_name",
				"enabled",
				"priority",
				"strategy",
				"pipeline",
				"source_id_values",
				"target_agents",
				"fallback_user",
				"modified",
			],
			order_by="priority asc, modified desc",
			limit_page_length=100,
		)
	}


def inspect_mi_agent_states() -> dict:
	agents = [
		"aman_mi@sriaas.com",
		"karan_drh@sriaas.com",
		"mandeep_mi@sriaas.com",
		"ankitchaudhary_mi@sriaas.com",
	]
	return {
		"states": frappe.get_all(
			"New Assignement System Agent State",
			filters={"agent": ["in", agents]},
			fields=[
				"name",
				"agent",
				"team",
				"active",
				"capacity",
				"current_open_leads",
				"allowed_pipelines",
				"allowed_sources",
				"allowed_campaigns",
				"shift_start",
				"shift_end",
			],
			order_by="agent asc, modified desc",
			limit_page_length=100,
		)
	}


def inspect_recent_pankaj_leads() -> dict:
	return {
		"pankaj_matches": frappe.get_all(
			"CRM Lead",
			or_filters=[
				{"first_name": ["like", "%Pankaj%"]},
				{"last_name": ["like", "%Kumar%"]},
				{"email": ["like", "%aksks88%"]},
				{"mobile_no": ["like", "%9308727739%"]},
			],
			fields=[
				"name",
				"creation",
				"lead_owner",
				"status",
				"sr_lead_pipeline",
				"sr_w_source_id",
				"first_name",
				"last_name",
				"email",
				"mobile_no",
			],
			order_by="creation desc",
			limit_page_length=20,
		),
		"latest_leads": frappe.get_all(
			"CRM Lead",
			fields=[
				"name",
				"creation",
				"lead_owner",
				"status",
				"sr_lead_pipeline",
				"sr_w_source_id",
				"first_name",
				"email",
				"mobile_no",
			],
			order_by="creation desc",
			limit_page_length=10,
		),
	}


def inspect_crm_notification(name: str) -> dict:
	if not frappe.db.exists("CRM Notification", name):
		return {"exists": False, "name": name}

	doc = frappe.get_doc("CRM Notification", name)
	out = {
		"exists": True,
		"notification": {
			"name": doc.name,
			"creation": str(doc.creation),
			"owner": doc.owner,
			"from_user": doc.from_user,
			"to_user": doc.to_user,
			"type": doc.type,
			"read": doc.read,
			"reference_doctype": doc.reference_doctype,
			"reference_name": doc.reference_name,
			"notification_type_doctype": doc.notification_type_doctype,
			"notification_type_doc": doc.notification_type_doc,
			"comment": doc.comment,
			"message": doc.message,
			"notification_text": doc.notification_text,
		},
	}

	if doc.reference_doctype == "CRM Lead" and doc.reference_name:
		out["lead"] = _get_lead_snapshot(doc.reference_name)
		out["assignment_queue_count"] = frappe.db.count("New Assignement System Queue", {"lead": doc.reference_name})
		out["assignment_log_count"] = frappe.db.count("New Assignement System Log", {"lead": doc.reference_name})
		out["open_todos"] = frappe.get_all(
			"ToDo",
			filters={
				"reference_type": "CRM Lead",
				"reference_name": doc.reference_name,
				"status": "Open",
			},
			fields=["name", "allocated_to", "owner", "description", "creation"],
			limit_page_length=20,
		)

	if doc.notification_type_doctype and doc.notification_type_doc:
		out["notification_source_exists"] = frappe.db.exists(
			doc.notification_type_doctype,
			doc.notification_type_doc,
		)
		if doc.notification_type_doctype == "WhatsApp Message":
			out["whatsapp_message"] = frappe.db.get_value(
				"WhatsApp Message",
				doc.notification_type_doc,
				["name", "type", "from", "to", "reference_doctype", "reference_name", "owner", "message"],
				as_dict=True,
			)
		elif doc.notification_type_doctype == "ToDo":
			out["todo"] = frappe.db.get_value(
				"ToDo",
				doc.notification_type_doc,
				["name", "allocated_to", "reference_type", "reference_name", "status", "owner", "description"],
				as_dict=True,
			)

	return out


def _get_lead_snapshot(lead: str) -> dict | None:
	if not frappe.db.exists("CRM Lead", lead):
		return None
	fields = [
		"name",
		"lead_owner",
		"status",
		"source",
		"sr_lead_pipeline",
		"sr_lead_platform",
		"sr_w_source_id",
		"first_name",
		"last_name",
		"email",
		"mobile_no",
	]
	return frappe.db.get_value("CRM Lead", lead, fields, as_dict=True)


def _delete_crm_notifications_for_lead(lead: str) -> None:
	if not frappe.db.exists("DocType", "CRM Notification"):
		return
	frappe.db.delete("CRM Notification", {"reference_doctype": "CRM Lead", "reference_name": lead})
	frappe.db.delete(
		"CRM Notification",
		{"notification_type_doctype": "CRM Lead", "notification_type_doc": lead},
	)


def inspect_assignment_artifacts(log_name: str | None = None, queue_name: str | None = None) -> dict:
	out = {}
	lead_names = set()

	if log_name and frappe.db.exists("New Assignement System Log", log_name):
		log_doc = frappe.get_doc("New Assignement System Log", log_name)
		out["log"] = {
			"name": log_doc.name,
			"lead": log_doc.lead,
			"action": log_doc.action,
			"status": log_doc.status,
			"old_owner": log_doc.old_owner,
			"new_owner": log_doc.new_owner,
			"rule": log_doc.rule,
			"queue": log_doc.queue,
			"triggered_by": log_doc.triggered_by,
			"reason": log_doc.reason,
			"metadata_snapshot": log_doc.metadata_snapshot,
		}
		lead_names.add(log_doc.lead)
	else:
		out["log"] = None

	if queue_name and frappe.db.exists("New Assignement System Queue", queue_name):
		queue_doc = frappe.get_doc("New Assignement System Queue", queue_name)
		out["queue"] = {
			"name": queue_doc.name,
			"lead": queue_doc.lead,
			"event_type": queue_doc.event_type,
			"status": queue_doc.status,
			"attempts": queue_doc.attempts,
			"rule": queue_doc.rule,
			"error": queue_doc.error,
			"metadata_snapshot": queue_doc.metadata_snapshot,
		}
		lead_names.add(queue_doc.lead)
	else:
		out["queue"] = None

	out["leads"] = {}
	for lead in sorted(filter(None, lead_names)):
		if not frappe.db.exists("CRM Lead", lead):
			out["leads"][lead] = None
			continue
		fields = [
			"name",
			"lead_owner",
			"status",
			"source",
			"sr_lead_pipeline",
			"sr_lead_platform",
			"sr_w_source_id",
			"first_name",
			"mobile_no",
		]
		out["leads"][lead] = frappe.db.get_value("CRM Lead", lead, fields, as_dict=True)

	return out


def run_non_matching_pipeline_queue_test() -> dict:
	settings_name = "New Assignement System Settings"
	previous_settings = {}
	lead_name = None

	def set_if_has(doc, fieldname: str, value):
		if frappe.get_meta(doc.doctype).has_field(fieldname):
			doc.set(fieldname, value)

	try:
		if frappe.db.exists("DocType", settings_name):
			for fieldname, value in {
				"auto_assign_on_insert": 1,
				"queue_enabled": 1,
			}.items():
				previous_settings[fieldname] = frappe.db.get_single_value(settings_name, fieldname)
				frappe.db.set_single_value(settings_name, fieldname, value)

		lead = frappe.new_doc("CRM Lead")
		lead.first_name = "CLA Non Matching Pipeline"
		lead.status = "Fresh"
		lead.source = "Google"
		set_if_has(lead, "sr_lead_pipeline", "Kidney LP Dom")
		set_if_has(lead, "sr_lead_platform", "Website")
		set_if_has(lead, "sr_w_source_id", "120250583820420012")
		set_if_has(lead, "mobile_no", "9000000099")
		lead.insert(ignore_permissions=True)
		lead_name = lead.name

		queue_count = frappe.db.count("New Assignement System Queue", {"lead": lead_name})
		log_count = frappe.db.count("New Assignement System Log", {"lead": lead_name})
		owner = frappe.db.get_value("CRM Lead", lead_name, "lead_owner")

		return {
			"ok": queue_count == 0 and log_count == 0 and not owner,
			"lead": lead_name,
			"lead_owner": owner,
			"queue_count": queue_count,
			"log_count": log_count,
		}
	finally:
		if lead_name and frappe.db.exists("CRM Lead", lead_name):
			if frappe.db.get_value("CRM Lead", lead_name, "lead_owner"):
				clear_lead_assignment(lead_name, reason="Non-matching pipeline test cleanup", triggered_by="Mock Test")
			_delete_crm_notifications_for_lead(lead_name)
			frappe.db.delete("ToDo", {"reference_type": "CRM Lead", "reference_name": lead_name})
			frappe.db.delete("DocShare", {"share_doctype": "CRM Lead", "share_name": lead_name})
			frappe.db.delete("New Assignement System Queue", {"lead": lead_name})
			frappe.db.delete("New Assignement System Log", {"lead": lead_name})
			frappe.delete_doc("CRM Lead", lead_name, force=True, ignore_permissions=True)
		if previous_settings:
			for fieldname, value in previous_settings.items():
				frappe.db.set_single_value(settings_name, fieldname, value)
			frappe.db.commit()


def run_prefilled_owner_non_matching_pipeline_test() -> dict:
	settings_name = "New Assignement System Settings"
	previous_settings = {}
	lead_name = None

	def set_if_has(doc, fieldname: str, value):
		if frappe.get_meta(doc.doctype).has_field(fieldname):
			doc.set(fieldname, value)

	try:
		if frappe.db.exists("DocType", settings_name):
			for fieldname, value in {
				"auto_assign_on_insert": 1,
				"queue_enabled": 1,
			}.items():
				previous_settings[fieldname] = frappe.db.get_single_value(settings_name, fieldname)
				frappe.db.set_single_value(settings_name, fieldname, value)

		lead = frappe.new_doc("CRM Lead")
		lead.first_name = "CLA Prefilled Owner Non Match"
		lead.status = "Fresh"
		lead.source = "Google"
		lead.lead_owner = "ankitchaudhary_mi@sriaas.com"
		set_if_has(lead, "sr_lead_pipeline", "Kidney LP Dom")
		set_if_has(lead, "sr_lead_platform", "Website")
		set_if_has(lead, "sr_w_source_id", "120250583820420012")
		set_if_has(lead, "mobile_no", "9000000199")
		lead.insert(ignore_permissions=True)
		lead_name = lead.name

		owner = frappe.db.get_value("CRM Lead", lead_name, "lead_owner")
		queue_count = frappe.db.count("New Assignement System Queue", {"lead": lead_name})
		log_count = frappe.db.count("New Assignement System Log", {"lead": lead_name})
		todo_count = frappe.db.count("ToDo", {"reference_type": "CRM Lead", "reference_name": lead_name})
		docshare_count = frappe.db.count("DocShare", {"share_doctype": "CRM Lead", "share_name": lead_name})
		notification_count = frappe.db.count(
			"CRM Notification",
			{"reference_doctype": "CRM Lead", "reference_name": lead_name},
		)

		return {
			"ok": not owner
			and queue_count == 0
			and log_count == 0
			and todo_count == 0
			and docshare_count == 0
			and notification_count == 0,
			"lead": lead_name,
			"lead_owner": owner,
			"queue_count": queue_count,
			"log_count": log_count,
			"todo_count": todo_count,
			"docshare_count": docshare_count,
			"crm_notification_count": notification_count,
		}
	finally:
		if lead_name and frappe.db.exists("CRM Lead", lead_name):
			if frappe.db.get_value("CRM Lead", lead_name, "lead_owner"):
				clear_lead_assignment(lead_name, reason="Prefilled owner test cleanup", triggered_by="Mock Test")
			_delete_crm_notifications_for_lead(lead_name)
			frappe.db.delete("ToDo", {"reference_type": "CRM Lead", "reference_name": lead_name})
			frappe.db.delete("DocShare", {"share_doctype": "CRM Lead", "share_name": lead_name})
			frappe.db.delete("New Assignement System Queue", {"lead": lead_name})
			frappe.db.delete("New Assignement System Log", {"lead": lead_name})
			frappe.delete_doc("CRM Lead", lead_name, force=True, ignore_permissions=True)
		if previous_settings:
			for fieldname, value in previous_settings.items():
				frappe.db.set_single_value(settings_name, fieldname, value)
		frappe.db.commit()


def run_live_insert_assignment_test() -> dict:
	from new_assignement_system.jobs import process_assignment_queue_item

	settings_name = "New Assignement System Settings"
	previous_settings = {}
	lead_name = None

	def set_if_has(doc, fieldname: str, value):
		if frappe.get_meta(doc.doctype).has_field(fieldname):
			doc.set(fieldname, value)

	try:
		if frappe.db.exists("DocType", settings_name):
			for fieldname, value in {
				"auto_assign_on_insert": 1,
				"queue_enabled": 1,
				"sync_todo": 1,
				"sync_docshare": 1,
			}.items():
				previous_settings[fieldname] = frappe.db.get_single_value(settings_name, fieldname)
				frappe.db.set_single_value(settings_name, fieldname, value)

		lead = frappe.new_doc("CRM Lead")
		lead.first_name = "CLA Live Insert Assignment"
		lead.status = "Fresh"
		lead.source = "Google"
		set_if_has(lead, "sr_lead_pipeline", "MI Meta Interakt")
		set_if_has(lead, "sr_lead_platform", "Website")
		set_if_has(lead, "sr_w_source_id", "120250723559390012")
		set_if_has(lead, "mobile_no", "9000000299")
		lead.insert(ignore_permissions=True)
		lead_name = lead.name

		queue_name = frappe.db.get_value("New Assignement System Queue", {"lead": lead_name}, "name")
		result = process_assignment_queue_item(queue_name) if queue_name else None
		owner = frappe.db.get_value("CRM Lead", lead_name, "lead_owner")
		queue_status = frappe.db.get_value("New Assignement System Queue", queue_name, "status") if queue_name else None
		log_count = frappe.db.count(
			"New Assignement System Log",
			{"lead": lead_name, "new_owner": "mandeep_mi@sriaas.com", "action": "Assigned"},
		)
		log_reason = frappe.db.get_value(
			"New Assignement System Log",
			{"lead": lead_name, "new_owner": "mandeep_mi@sriaas.com", "action": "Assigned"},
			"reason",
			order_by="creation desc",
		)
		todo_count = frappe.db.count(
			"ToDo",
			{
				"reference_type": "CRM Lead",
				"reference_name": lead_name,
				"allocated_to": "mandeep_mi@sriaas.com",
				"status": "Open",
			},
		)
		standard_rule_todo_count = frappe.db.count(
			"ToDo",
			{
				"reference_type": "CRM Lead",
				"reference_name": lead_name,
				"assignment_rule": ["is", "set"],
			},
		)
		notification_count = frappe.db.count(
			"CRM Notification",
			{"reference_doctype": "CRM Lead", "reference_name": lead_name},
		)

		return {
			"ok": owner == "mandeep_mi@sriaas.com"
			and queue_status == "Assigned"
			and log_count >= 1
			and todo_count == 1
			and standard_rule_todo_count == 0
			and notification_count == 1
			and log_reason == "Auto assignment by rule Mi Lead Rule-mandeep",
			"lead": lead_name,
			"queue": queue_name,
			"engine_result": result,
			"lead_owner": owner,
			"queue_status": queue_status,
			"assigned_log_count": log_count,
			"log_reason": log_reason,
			"todo_count": todo_count,
			"standard_rule_todo_count": standard_rule_todo_count,
			"crm_notification_count": notification_count,
		}
	finally:
		if lead_name and frappe.db.exists("CRM Lead", lead_name):
			if frappe.db.get_value("CRM Lead", lead_name, "lead_owner"):
				clear_lead_assignment(lead_name, reason="Live insert test cleanup", triggered_by="Mock Test")
			_delete_crm_notifications_for_lead(lead_name)
			frappe.db.delete("ToDo", {"reference_type": "CRM Lead", "reference_name": lead_name})
			frappe.db.delete("DocShare", {"share_doctype": "CRM Lead", "share_name": lead_name})
			frappe.db.delete("New Assignement System Queue", {"lead": lead_name})
			frappe.db.delete("New Assignement System Log", {"lead": lead_name})
			frappe.delete_doc("CRM Lead", lead_name, force=True, ignore_permissions=True)
		if previous_settings:
			for fieldname, value in previous_settings.items():
				frappe.db.set_single_value(settings_name, fieldname, value)
		frappe.db.commit()


def run_mock_assignment_test() -> dict:
	created: list[str] = []
	results = []
	settings_name = "New Assignement System Settings"
	previous_settings = {}

	def set_if_has(doc, fieldname: str, value):
		if frappe.get_meta(doc.doctype).has_field(fieldname):
			doc.set(fieldname, value)

	def cleanup() -> None:
		for lead in list(created):
			if not frappe.db.exists("CRM Lead", lead):
				continue
			if frappe.db.get_value("CRM Lead", lead, "lead_owner"):
				clear_lead_assignment(lead, reason="Mock test cleanup", triggered_by="Mock Test")
			_delete_crm_notifications_for_lead(lead)
			frappe.db.delete("ToDo", {"reference_type": "CRM Lead", "reference_name": lead})
			frappe.db.delete("DocShare", {"share_doctype": "CRM Lead", "share_name": lead})
			frappe.db.delete("New Assignement System Queue", {"lead": lead})
			frappe.db.delete("New Assignement System Log", {"lead": lead})
			frappe.delete_doc("CRM Lead", lead, force=True, ignore_permissions=True)
		frappe.db.commit()

	def reset_assignment_state(lead: str) -> None:
		if frappe.db.get_value("CRM Lead", lead, "lead_owner"):
			clear_lead_assignment(lead, reason="Mock test reset", triggered_by="Mock Test")

		if frappe.db.has_column("CRM Lead", "team"):
			frappe.db.set_value("CRM Lead", lead, "team", None, update_modified=False)
		frappe.db.set_value("CRM Lead", lead, "lead_owner", None, update_modified=False)
		_delete_crm_notifications_for_lead(lead)
		frappe.db.delete("ToDo", {"reference_type": "CRM Lead", "reference_name": lead})
		frappe.db.delete("DocShare", {"share_doctype": "CRM Lead", "share_name": lead})
		frappe.db.delete("New Assignement System Queue", {"lead": lead})
		frappe.db.delete("New Assignement System Log", {"lead": lead})

	try:
		if frappe.db.exists("DocType", settings_name):
			for fieldname, value in {
				"auto_assign_on_insert": 0,
				"sync_todo": 1,
				"sync_docshare": 1,
			}.items():
				previous_settings[fieldname] = frappe.db.get_single_value(settings_name, fieldname)
				frappe.db.set_single_value(settings_name, fieldname, value)

		for index, (source_id, expected_owner) in enumerate(RULE_CASES, start=1):
			lead = frappe.new_doc("CRM Lead")
			lead.first_name = f"CLA Mock {index}"
			lead.status = "New"
			set_if_has(lead, "sr_lead_pipeline", "MI Meta Interakt")
			set_if_has(lead, "sr_lead_platform", "Interakt")
			set_if_has(lead, "sr_w_source_id", source_id)
			set_if_has(lead, "mobile_no", f"90000000{index:02d}")
			previous_disable_hooks = getattr(frappe.flags, "new_assignement_system_disable_hooks", False)
			frappe.flags.new_assignement_system_disable_hooks = True
			try:
				lead.insert(ignore_permissions=True)
				created.append(lead.name)
			finally:
				frappe.flags.new_assignement_system_disable_hooks = previous_disable_hooks

			reset_assignment_state(lead.name)
			result = auto_assign_lead(lead.name, event_type="Mock Test")
			owner = frappe.db.get_value("CRM Lead", lead.name, "lead_owner")
			todo_count = frappe.db.count(
				"ToDo",
				{
					"reference_type": "CRM Lead",
					"reference_name": lead.name,
					"allocated_to": expected_owner,
					"status": "Open",
				},
			)
			share_count = frappe.db.count(
				"DocShare",
				{"share_doctype": "CRM Lead", "share_name": lead.name, "user": expected_owner},
			)
			log_count = frappe.db.count(
				"New Assignement System Log",
				{"lead": lead.name, "new_owner": expected_owner},
			)
			ok = (
				result.get("status") == "ok"
				and owner == expected_owner
				and todo_count == 1
				and share_count == 1
				and log_count >= 1
			)
			results.append(
				{
					"source_id": source_id,
					"expected_owner": expected_owner,
					"actual_owner": owner,
					"engine_status": result.get("status"),
					"todo_count": todo_count,
					"share_count": share_count,
					"log_count": log_count,
					"ok": ok,
				}
			)

		source_id_docfield = frappe.db.exists(
			"DocField",
			{"parent": "New Assignement System Rule", "fieldname": "source_id"},
		)
		source_id_column = frappe.db.sql(
			"""
			select count(*)
			from information_schema.columns
			where table_schema = database()
			  and table_name = 'tabNew Assignement System Rule'
			  and column_name = 'source_id'
			"""
		)[0][0]

		return {
			"ok": all(row["ok"] for row in results) and not source_id_docfield and not source_id_column,
			"assignment_results": results,
			"source_id_field_removed": not bool(source_id_docfield),
			"source_id_column_removed": not bool(source_id_column),
		}
	finally:
		cleanup()
		if previous_settings:
			for fieldname, value in previous_settings.items():
				frappe.db.set_single_value(settings_name, fieldname, value)
			frappe.db.commit()
