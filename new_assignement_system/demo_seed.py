from __future__ import annotations

from collections import Counter

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import now_datetime

DEMO_PREFIX = "NAS Demo"
SOURCES = ["Auto Website", "Auto Facebook", "Auto Google Ads", "Auto Referral"]
USERS = [
	"nas-demo-website@example.test",
	"nas-demo-facebook@example.test",
	"nas-demo-google@example.test",
	"nas-demo-referral@example.test",
]
WHATSAPP_SOURCE_ID = "120250583820420012"
WHATSAPP_SOURCE_URL = "https://fb.me/5z965mhuG"
WHATSAPP_CTWA_CLID = (
	"AfeIjQNzVJ4HaTQ5T_Oe4kNGgTHLvRSjiybMa-OLOvlqaBvEq9rHUEDZz7I8I0i-ddoy_Rna-J6gb5MxP9vHpQ30i7vXJp1iXPW4b0RjOSsi-JHsLu3SE2Pdv6ludcXdNq0fdD-9jw"
)
WHATSAPP_SAMPLE_SOURCE_IDS = [
	"120250583820420012",
	"120250583820420013",
	"120250583820420014",
	"120250583820420015",
	"120250583820420016",
	"120250583820420017",
	"120250583820420018",
	"120250583820420019",
	"120250583820420020",
	"120250583820420021",
]


def seed_rules_and_test_leads() -> dict:
	"""Create visible records in /app/new-assignement-system-rule and test routing."""
	from new_assignement_system.engine.service import auto_assign_lead

	_ensure_lead_fields()
	_ensure_masters()
	_ensure_users_and_sessions()
	_enable_settings()
	_disable_auto_crm_lead_assigner()
	_delete_demo_rules()
	rules = _create_rules()

	results = []
	for idx, spec in enumerate(_lead_specs(), start=1):
		frappe.flags.new_assignement_system_in_progress = True
		frappe.flags.auto_crm_lead_assigner_in_progress = True
		try:
			lead = frappe.get_doc(
				{
					"doctype": "CRM Lead",
					"first_name": f"{DEMO_PREFIX} Lead {idx}",
					"lead_name": f"{DEMO_PREFIX} Lead {idx}",
					"status": "New",
					"source": spec["source"],
					"sr_lead_pipeline": spec["pipeline"],
					"lead_temperature": spec["temperature"],
					"lead_score": spec["score"],
				}
			)
			lead.insert(ignore_permissions=True, ignore_mandatory=True)
		finally:
			frappe.flags.new_assignement_system_in_progress = False
			frappe.flags.auto_crm_lead_assigner_in_progress = False

		assignment = auto_assign_lead(lead.name, event_type="Manual Test")
		owner = frappe.db.get_value("CRM Lead", lead.name, "lead_owner")
		results.append(
			{
				"lead": lead.name,
				"source": spec["source"],
				"pipeline": spec["pipeline"],
				"lead_temperature": spec["temperature"],
				"lead_score": spec["score"],
				"assigned_to": owner,
				"assignment_status": assignment.get("status"),
			}
		)

	return {
		"doctype": "New Assignement System Rule",
		"rules_created": rules,
		"rule_count": frappe.db.count("New Assignement System Rule", {"rule_name": ["like", f"{DEMO_PREFIX}%"]}),
		"test_leads_created": len(results),
		"assigned": sum(1 for row in results if row["assigned_to"]),
		"distribution": dict(Counter(row["assigned_to"] for row in results)),
		"results": results,
	}


def test_normal_insert_assignment() -> dict:
	"""Create one lead normally, commit, and verify after_insert hook assigns owner/source."""
	seed_rules_and_test_leads()

	lead = frappe.get_doc(
		{
			"doctype": "CRM Lead",
			"first_name": f"{DEMO_PREFIX} Auto Hook Lead",
			"lead_name": f"{DEMO_PREFIX} Auto Hook Lead",
			"status": "New",
			"source": "Auto Website",
			"sr_lead_pipeline": "High Intent",
			"lead_temperature": "Hot",
			"lead_score": 91,
		}
	)
	lead.insert(ignore_permissions=True, ignore_mandatory=True)
	frappe.db.commit()

	return {
		"lead": lead.name,
		"lead_owner": frappe.db.get_value("CRM Lead", lead.name, "lead_owner"),
		"source": frappe.db.get_value("CRM Lead", lead.name, "source"),
		"expected_owner": USERS[0],
		"expected_source": "Auto Website",
	}


def clear_rule_source_filters() -> dict:
	rules = frappe.get_all(
		"New Assignement System Rule",
		filters={"source": ["!=", ""]},
		fields=["name", "source", "target_source"],
		limit_page_length=0,
	)
	for rule in rules:
		frappe.db.set_value("New Assignement System Rule", rule.name, "source", None)
	frappe.db.commit()
	return {
		"updated": len(rules),
		"remaining_with_source": frappe.db.count("New Assignement System Rule", {"source": ["!=", ""]}),
		"target_source_kept": {
			rule.name: rule.target_source
			for rule in rules
			if rule.target_source
		},
	}


def _ensure_lead_fields() -> None:
	create_custom_fields(
		{
			"CRM Lead": [
				{
					"fieldname": "sr_lead_pipeline",
					"label": "SR Lead Pipeline",
					"fieldtype": "Select",
					"options": "\nHigh Intent\nNurture\nPaid Campaign\nPartner Referral\nKidney LP Dom\nMI Meta Interakt",
					"insert_after": "source",
				},
				{
					"fieldname": "lead_temperature",
					"label": "Lead Temperature",
					"fieldtype": "Select",
					"options": "\nHot\nWarm\nCold",
					"insert_after": "sr_lead_pipeline",
				},
				{
					"fieldname": "lead_score",
					"label": "Lead Score",
					"fieldtype": "Int",
					"insert_after": "lead_temperature",
				},
			]
		},
		ignore_validate=True,
	)


def _ensure_whatsapp_lead_fields() -> None:
	create_custom_fields(
		{
			"CRM Lead": [
				{
					"fieldname": "sr_w_source_id",
					"label": "WhatsApp Source ID",
					"fieldtype": "Data",
					"insert_after": "lead_score",
				},
				{
					"fieldname": "sr_w_source_url",
					"label": "WhatsApp Source URL",
					"fieldtype": "Data",
					"insert_after": "sr_w_source_id",
				},
				{
					"fieldname": "sr_w_ctwa_clid",
					"label": "WhatsApp CTWA CLID",
					"fieldtype": "Long Text",
					"insert_after": "sr_w_source_url",
				},
			]
		},
		ignore_validate=True,
	)


def _ensure_masters() -> None:
	source_dt = frappe.get_meta("CRM Lead").get_field("source").options
	status_dt = frappe.get_meta("CRM Lead").get_field("status").options
	for source in SOURCES:
		_ensure_named_master(source_dt, source)
		_ensure_sr_lead_source(source)
	for pipeline in ["High Intent", "Nurture", "Paid Campaign", "Partner Referral"]:
		_ensure_sr_lead_pipeline(pipeline)
	_ensure_named_master(status_dt, "New")


def _ensure_named_master(doctype: str, value: str) -> None:
	if frappe.db.exists(doctype, value):
		return
	meta = frappe.get_meta(doctype)
	doc = frappe.new_doc(doctype)
	autoname = meta.autoname or ""
	if autoname.startswith("field:"):
		doc.set(autoname.split(":", 1)[1], value)
	elif meta.title_field:
		doc.set(meta.title_field, value)
	else:
		doc.name = value
	for field in meta.get("fields"):
		if field.reqd and not doc.get(field.fieldname) and field.fieldtype in {"Data", "Select"}:
			doc.set(field.fieldname, value)
	doc.insert(ignore_permissions=True)


def _ensure_sr_lead_source(source: str) -> None:
	if frappe.db.exists("SR Lead Source", source):
		return
	frappe.get_doc(
		{
			"doctype": "SR Lead Source",
			"sr_source_name": source,
			"is_active": 1,
		}
	).insert(ignore_permissions=True)

def set_source_id_filters_and_test() -> dict:
	"""Clear Status filters and add sample Source ID Values to demo rules, then verify routing."""
	_ensure_lead_fields()
	_ensure_masters()
	_ensure_users_and_sessions()
	_enable_settings()
	_disable_auto_crm_lead_assigner()

	source_id_map = {
		f"{DEMO_PREFIX} - Website Hot High Intent": "WEB-001\nWEB-002",
		f"{DEMO_PREFIX} - Facebook Warm Nurture": "FB-001\nFB-002",
		f"{DEMO_PREFIX} - Google Paid Campaign": "GADS-001\nGADS-002",
		f"{DEMO_PREFIX} - Referral Partner": "REF-001\nREF-002",
	}
	updated = []
	for rule_name, source_ids in source_id_map.items():
		if not frappe.db.exists("New Assignement System Rule", rule_name):
			continue
		frappe.db.set_value(
			"New Assignement System Rule",
			rule_name,
			{
				"status": None,
				"source_id_values": source_ids,
			},
		)
		updated.append(rule_name)
	frappe.db.commit()

	tests = [
		{
			"rule": f"{DEMO_PREFIX} - Website Hot High Intent",
			"source": "Unqualified",
			"pipeline": "High Intent",
			"source_id": "WEB-001",
			"temperature": "Hot",
			"score": 91,
			"expected_owner": USERS[0],
			"expected_source": "Auto Website",
		},
		{
			"rule": f"{DEMO_PREFIX} - Facebook Warm Nurture",
			"source": "Unqualified",
			"pipeline": "Nurture",
			"source_id": "FB-002",
			"temperature": "Warm",
			"score": 60,
			"expected_owner": USERS[1],
			"expected_source": "Auto Facebook",
		},
	]
	results = [_create_source_id_test_lead(spec, idx) for idx, spec in enumerate(tests, start=1)]
	return {
		"rules_updated": updated,
		"remaining_with_status": frappe.db.count("New Assignement System Rule", {"status": ["!=", ""]}),
		"results": results,
	}


def add_whatsapp_source_id_and_create_dummy_leads() -> dict:
	"""Add the supplied WhatsApp source id to demo rules and create dummy matching leads."""
	_ensure_lead_fields()
	_ensure_whatsapp_lead_fields()
	_ensure_masters()
	_ensure_users_and_sessions()
	_enable_settings()
	_disable_auto_crm_lead_assigner()

	rules = [
		f"{DEMO_PREFIX} - Website Hot High Intent",
		f"{DEMO_PREFIX} - Facebook Warm Nurture",
		f"{DEMO_PREFIX} - Google Paid Campaign",
		f"{DEMO_PREFIX} - Referral Partner",
	]
	updated = []
	for rule_name in rules:
		if not frappe.db.exists("New Assignement System Rule", rule_name):
			continue
		existing = frappe.db.get_value("New Assignement System Rule", rule_name, "source_id_values") or ""
		values = {part.strip() for part in existing.replace(",", "\n").splitlines() if part.strip()}
		values.add(WHATSAPP_SOURCE_ID)
		frappe.db.set_value(
			"New Assignement System Rule",
			rule_name,
			{
				"status": None,
				"source_id_values": "\n".join(sorted(values)),
			},
		)
		updated.append(rule_name)
	frappe.db.commit()

	specs = [
		{
			"pipeline": "High Intent",
			"source": "Unqualified",
			"temperature": "Hot",
			"score": 96,
			"expected_owner": USERS[0],
			"expected_source": "Auto Website",
		},
		{
			"pipeline": "Nurture",
			"source": "Unqualified",
			"temperature": "Warm",
			"score": 58,
			"expected_owner": USERS[1],
			"expected_source": "Auto Facebook",
		},
		{
			"pipeline": "Paid Campaign",
			"source": "Unqualified",
			"temperature": "Hot",
			"score": 83,
			"expected_owner": USERS[2],
			"expected_source": "Auto Google Ads",
		},
	]
	results = [_create_whatsapp_dummy_lead(spec, idx) for idx, spec in enumerate(specs, start=1)]
	return {
		"whatsapp_source_id": WHATSAPP_SOURCE_ID,
		"rules_updated": updated,
		"dummy_leads_created": len(results),
		"results": results,
	}


def add_10_whatsapp_source_ids_and_create_10_leads() -> dict:
	"""Add 10 sample WhatsApp source IDs into demo rules and create 10 matching CRM Leads."""
	_ensure_lead_fields()
	_ensure_whatsapp_lead_fields()
	_ensure_masters()
	_ensure_users_and_sessions()
	_enable_settings()
	_disable_auto_crm_lead_assigner()

	rule_names = [
		f"{DEMO_PREFIX} - Website Hot High Intent",
		f"{DEMO_PREFIX} - Facebook Warm Nurture",
		f"{DEMO_PREFIX} - Google Paid Campaign",
		f"{DEMO_PREFIX} - Referral Partner",
	]
	updated = []
	for rule_name in rule_names:
		if not frappe.db.exists("New Assignement System Rule", rule_name):
			continue
		existing = frappe.db.get_value("New Assignement System Rule", rule_name, "source_id_values") or ""
		values = {part.strip() for part in existing.replace(",", "\n").splitlines() if part.strip()}
		values.update(WHATSAPP_SAMPLE_SOURCE_IDS)
		frappe.db.set_value(
			"New Assignement System Rule",
			rule_name,
			{
				"status": None,
				"source_id_values": "\n".join(sorted(values)),
			},
		)
		updated.append(rule_name)
	frappe.db.commit()

	specs = [
		{"pipeline": "High Intent", "source": "Unqualified", "temperature": "Hot", "score": 95, "expected_owner": USERS[0], "expected_source": "Auto Website"},
		{"pipeline": "High Intent", "source": "Unqualified", "temperature": "Hot", "score": 88, "expected_owner": USERS[0], "expected_source": "Auto Website"},
		{"pipeline": "Nurture", "source": "Unqualified", "temperature": "Warm", "score": 55, "expected_owner": USERS[1], "expected_source": "Auto Facebook"},
		{"pipeline": "Nurture", "source": "Unqualified", "temperature": "Hot", "score": 70, "expected_owner": USERS[1], "expected_source": "Auto Facebook"},
		{"pipeline": "Paid Campaign", "source": "Unqualified", "temperature": "Warm", "score": 72, "expected_owner": USERS[2], "expected_source": "Auto Google Ads"},
		{"pipeline": "Paid Campaign", "source": "Unqualified", "temperature": "Hot", "score": 81, "expected_owner": USERS[2], "expected_source": "Auto Google Ads"},
		{"pipeline": "Partner Referral", "source": "Unqualified", "temperature": "Warm", "score": 65, "expected_owner": USERS[3], "expected_source": "Auto Referral"},
		{"pipeline": "Partner Referral", "source": "Unqualified", "temperature": "Cold", "score": 52, "expected_owner": USERS[3], "expected_source": "Auto Referral"},
		{"pipeline": "High Intent", "source": "Unqualified", "temperature": "Hot", "score": 99, "expected_owner": USERS[0], "expected_source": "Auto Website"},
		{"pipeline": "Paid Campaign", "source": "Unqualified", "temperature": "Warm", "score": 77, "expected_owner": USERS[2], "expected_source": "Auto Google Ads"},
	]
	results = []
	for idx, spec in enumerate(specs, start=1):
		spec = spec.copy()
		spec["source_id"] = WHATSAPP_SAMPLE_SOURCE_IDS[idx - 1]
		spec["source_url"] = f"https://fb.me/sample-{idx:02d}"
		spec["ctwa_clid"] = f"{WHATSAPP_CTWA_CLID}-{idx:02d}"
		results.append(_create_whatsapp_dummy_lead(spec, idx))

	return {
		"sample_source_ids_added": WHATSAPP_SAMPLE_SOURCE_IDS,
		"rules_updated": updated,
		"dummy_leads_created": len(results),
		"assigned": sum(1 for row in results if row["lead_owner"]),
		"results": results,
	}


def divide_10_source_ids_across_rules_and_test() -> dict:
	"""Split the 10 sample source IDs across 4 rules and verify owner/source routing."""
	_ensure_lead_fields()
	_ensure_whatsapp_lead_fields()
	_ensure_masters()
	_ensure_users_and_sessions()
	_enable_settings()
	_disable_auto_crm_lead_assigner()

	rule_source_ids = {
		f"{DEMO_PREFIX} - Website Hot High Intent": WHATSAPP_SAMPLE_SOURCE_IDS[0:3],
		f"{DEMO_PREFIX} - Facebook Warm Nurture": WHATSAPP_SAMPLE_SOURCE_IDS[3:5],
		f"{DEMO_PREFIX} - Google Paid Campaign": WHATSAPP_SAMPLE_SOURCE_IDS[5:8],
		f"{DEMO_PREFIX} - Referral Partner": WHATSAPP_SAMPLE_SOURCE_IDS[8:10],
	}
	for rule_name, source_ids in rule_source_ids.items():
		if not frappe.db.exists("New Assignement System Rule", rule_name):
			continue
		frappe.db.set_value(
			"New Assignement System Rule",
			rule_name,
			{
				"status": None,
				"source_id_values": "\n".join(source_ids),
			},
		)
	frappe.db.commit()

	test_specs = [
		{"pipeline": "High Intent", "temperature": "Hot", "score": 95, "owner": USERS[0], "source": "Auto Website"},
		{"pipeline": "High Intent", "temperature": "Hot", "score": 91, "owner": USERS[0], "source": "Auto Website"},
		{"pipeline": "High Intent", "temperature": "Hot", "score": 88, "owner": USERS[0], "source": "Auto Website"},
		{"pipeline": "Nurture", "temperature": "Warm", "score": 55, "owner": USERS[1], "source": "Auto Facebook"},
		{"pipeline": "Nurture", "temperature": "Hot", "score": 70, "owner": USERS[1], "source": "Auto Facebook"},
		{"pipeline": "Paid Campaign", "temperature": "Warm", "score": 72, "owner": USERS[2], "source": "Auto Google Ads"},
		{"pipeline": "Paid Campaign", "temperature": "Hot", "score": 81, "owner": USERS[2], "source": "Auto Google Ads"},
		{"pipeline": "Paid Campaign", "temperature": "Warm", "score": 77, "owner": USERS[2], "source": "Auto Google Ads"},
		{"pipeline": "Partner Referral", "temperature": "Warm", "score": 65, "owner": USERS[3], "source": "Auto Referral"},
		{"pipeline": "Partner Referral", "temperature": "Cold", "score": 52, "owner": USERS[3], "source": "Auto Referral"},
	]
	results = []
	for idx, (source_id, spec) in enumerate(zip(WHATSAPP_SAMPLE_SOURCE_IDS, test_specs, strict=True), start=1):
		spec = {
			"pipeline": spec["pipeline"],
			"source": "Unqualified",
			"temperature": spec["temperature"],
			"score": spec["score"],
			"source_id": source_id,
			"source_url": f"https://fb.me/divided-{idx:02d}",
			"ctwa_clid": f"{WHATSAPP_CTWA_CLID}-divided-{idx:02d}",
			"expected_owner": spec["owner"],
			"expected_source": spec["source"],
		}
		results.append(_create_whatsapp_dummy_lead(spec, idx))

	return {
		"rule_source_ids": rule_source_ids,
		"dummy_leads_created": len(results),
		"assigned": sum(1 for row in results if row["lead_owner"]),
		"all_expected": all(
			row["lead_owner"] == row["expected_owner"] and row["source_after_assignment"] == row["expected_source"]
			for row in results
		),
		"results": results,
	}


def fix_rules_for_source_id_only_and_assign_postman_lead() -> dict:
	"""Make demo rules match API payloads by pipeline + sr_w_source_id only, then assign the reported lead."""
	from new_assignement_system.engine.service import auto_assign_lead

	lead_name = "CRM-LEAD-2026-02193"
	_ensure_lead_fields()
	_ensure_whatsapp_lead_fields()
	_ensure_masters()
	_ensure_users_and_sessions()
	_enable_settings()
	_disable_auto_crm_lead_assigner()

	rule_source_ids = {
		f"{DEMO_PREFIX} - Website Hot High Intent": WHATSAPP_SAMPLE_SOURCE_IDS[0:3],
		f"{DEMO_PREFIX} - Facebook Warm Nurture": WHATSAPP_SAMPLE_SOURCE_IDS[3:5],
		f"{DEMO_PREFIX} - Google Paid Campaign": WHATSAPP_SAMPLE_SOURCE_IDS[5:8],
		f"{DEMO_PREFIX} - Referral Partner": WHATSAPP_SAMPLE_SOURCE_IDS[8:10],
	}
	updated = []
	for rule_name, source_ids in rule_source_ids.items():
		if not frappe.db.exists("New Assignement System Rule", rule_name):
			continue
		frappe.db.set_value(
			"New Assignement System Rule",
			rule_name,
			{
				"status": None,
				"source": None,
				"source_id_values": "\n".join(source_ids),
				"lead_score_min": 0,
				"lead_score_max": 0,
			},
		)
		for child in frappe.get_all(
			"New Assignement System Metadata Filter",
			filters={
				"parent": rule_name,
				"parenttype": "New Assignement System Rule",
				"parentfield": "metadata_filters",
			},
			pluck="name",
		):
			frappe.delete_doc("New Assignement System Metadata Filter", child, ignore_permissions=True, force=True)
		updated.append(rule_name)
	frappe.db.commit()

	before = _lead_assignment_snapshot(lead_name)
	result = auto_assign_lead(lead_name, event_type="Manual Fix Existing Lead")
	frappe.db.commit()
	after = _lead_assignment_snapshot(lead_name)

	return {
		"rules_updated": updated,
		"assignment_result": result,
		"before": before,
		"after": after,
		"queue_count_for_lead": frappe.db.count("New Assignement System Queue", {"lead": lead_name}),
		"log_count_for_lead": frappe.db.count("New Assignement System Log", {"lead": lead_name}),
	}


def create_postman_payload_test_lead() -> dict:
	"""Create a lead shaped like the user's curl payload and let insert hooks assign it."""
	_ensure_lead_fields()
	_ensure_whatsapp_lead_fields()
	_ensure_masters()
	_ensure_users_and_sessions()
	_enable_settings()
	_disable_auto_crm_lead_assigner()

	lead = frappe.get_doc(
		{
			"doctype": "CRM Lead",
			"first_name": "Hello",
			"last_name": "Kumar Singh",
			"lead_name": "Hello Kumar Singh Hook Test",
			"email": "aksks81+hooktest@gmail.com",
			"mobile_no": "9999888882",
			"status": "Fresh",
			"sr_lead_pipeline": "Nurture",
			"sr_lead_platform": "WhatsApp",
			"sr_lead_country": "India",
			"sr_lead_message": "Hi myself is a patient of Parkinsons disease and looking for best treatment Can you help me",
			"sr_w_source_id": "120250583820420015",
			"sr_w_source_url": WHATSAPP_SOURCE_URL,
			"sr_w_ctwa_clid": WHATSAPP_CTWA_CLID,
		}
	)
	lead.insert(ignore_permissions=True, ignore_mandatory=True)
	frappe.db.commit()
	return {
		"lead": lead.name,
		"after": _lead_assignment_snapshot(lead.name),
		"queue_count_for_lead": frappe.db.count("New Assignement System Queue", {"lead": lead.name}),
		"log_count_for_lead": frappe.db.count("New Assignement System Log", {"lead": lead.name}),
	}


def fix_log_jjfbdtsqba_lead() -> dict:
	"""Fix broad demo filters that caused log jjfbdtsqba and reassign its lead."""
	from new_assignement_system.engine.service import auto_assign_lead

	lead_name = "CRM-LEAD-2026-02202"
	rule_source_ids = {
		f"{DEMO_PREFIX} - Website Hot High Intent": WHATSAPP_SAMPLE_SOURCE_IDS[0:3],
		f"{DEMO_PREFIX} - Facebook Warm Nurture": WHATSAPP_SAMPLE_SOURCE_IDS[3:5],
		f"{DEMO_PREFIX} - Google Paid Campaign": WHATSAPP_SAMPLE_SOURCE_IDS[5:8],
		f"{DEMO_PREFIX} - Referral Partner": WHATSAPP_SAMPLE_SOURCE_IDS[8:10],
	}
	for rule, source_ids in rule_source_ids.items():
		if not frappe.db.exists("New Assignement System Rule", rule):
			continue
		frappe.db.set_value(
			"New Assignement System Rule",
			rule,
			{
				"status": None,
				"source": None,
				"source_id_values": "\n".join(source_ids),
				"campaign": None,
				"campaign_values": None,
				"disposition": None,
				"lead_score_min": 0,
				"lead_score_max": 0,
			},
		)
	frappe.db.set_value("CRM Lead", lead_name, "lead_owner", None)
	frappe.db.commit()
	result = auto_assign_lead(lead_name, event_type="Manual Fix Log jjfbdtsqba")
	frappe.db.commit()
	return {
		"original_log": "jjfbdtsqba",
		"assignment_result": result,
		"after": _lead_assignment_snapshot(lead_name),
		"log_count_for_lead": frappe.db.count("New Assignement System Log", {"lead": lead_name}),
	}


def test_any_configured_filter_matching() -> dict:
	"""Verify rules can match by any configured filter value, not only all filters together."""
	from new_assignement_system.engine.service import auto_assign_lead

	_ensure_lead_fields()
	_ensure_whatsapp_lead_fields()
	_ensure_masters()
	_ensure_users_and_sessions()
	_enable_settings()
	_disable_auto_crm_lead_assigner()

	# Keep multiple filters configured on the Nurture rule. Each test lead below
	# intentionally matches only one of those filters.
	rule_name = f"{DEMO_PREFIX} - Facebook Warm Nurture"
	frappe.db.set_value(
		"New Assignement System Rule",
		rule_name,
		{
			"pipeline": "Nurture",
			"source_id_values": "120250583820420015\n120250583820420016",
			"source": "Whatsapp",
			"status": "Fresh",
			"filter_match_mode": "Match Any Configured Filter",
			"target_source": "Auto Facebook",
			"lead_score_min": 0,
			"lead_score_max": 0,
			"only_if_unassigned": 1,
		},
	)
	frappe.db.commit()

	test_payloads = [
		{
			"label": "pipeline_only",
			"status": "Cold",
			"source": "Unqualified",
			"pipeline": "Nurture",
			"source_id": "NO-SOURCE-ID-MATCH-01",
		},
		{
			"label": "source_id_only",
			"status": "Cold",
			"source": "Unqualified",
			"pipeline": "",
			"source_id": "120250583820420015",
		},
		{
			"label": "source_only",
			"status": "Cold",
			"source": "Whatsapp",
			"pipeline": "",
			"source_id": "NO-SOURCE-ID-MATCH-02",
		},
		{
			"label": "status_only",
			"status": "Fresh",
			"source": "Unqualified",
			"pipeline": "",
			"source_id": "NO-SOURCE-ID-MATCH-03",
		},
	]
	results = []
	for idx, payload in enumerate(test_payloads, start=1):
		_ensure_named_master(frappe.get_meta("CRM Lead").get_field("source").options, payload["source"])
		_ensure_named_master(frappe.get_meta("CRM Lead").get_field("status").options, payload["status"])
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": f"{DEMO_PREFIX} Any Filter {idx}",
				"lead_name": f"{DEMO_PREFIX} Any Filter {idx}",
				"status": payload["status"],
				"source": payload["source"],
				"sr_lead_pipeline": payload["pipeline"],
				"sr_w_source_id": payload["source_id"],
				"sr_w_source_url": f"https://fb.me/any-filter-{idx}",
				"sr_w_ctwa_clid": f"{WHATSAPP_CTWA_CLID}-any-filter-{idx}",
			}
		)
		lead.insert(ignore_permissions=True, ignore_mandatory=True)
		assignment = auto_assign_lead(lead.name, event_type="Manual Any Filter Test")
		results.append(
			{
				"label": payload["label"],
				"lead": lead.name,
				"assignment_status": assignment.get("status"),
				"lead_owner": frappe.db.get_value("CRM Lead", lead.name, "lead_owner"),
				"source_after_assignment": frappe.db.get_value("CRM Lead", lead.name, "source"),
			}
		)

	return {
		"rule": rule_name,
		"expected_owner": USERS[1],
		"expected_source": "Auto Facebook",
		"all_expected": all(
			row["lead_owner"] == USERS[1] and row["source_after_assignment"] == "Auto Facebook"
			for row in results
		),
		"results": results,
	}


def _lead_assignment_snapshot(lead_name: str) -> dict:
	fields = [
		"name",
		"lead_owner",
		"source",
		"status",
		"sr_lead_pipeline",
		"sr_w_source_id",
		"sr_w_source_url",
		"sr_w_ctwa_clid",
	]
	return frappe.db.get_value("CRM Lead", lead_name, fields, as_dict=True) or {}


def _create_source_id_test_lead(spec: dict, idx: int) -> dict:
	from new_assignement_system.engine.service import auto_assign_lead

	_ensure_named_master(frappe.get_meta("CRM Lead").get_field("source").options, spec["source"])
	lead = frappe.get_doc(
		{
			"doctype": "CRM Lead",
			"first_name": f"{DEMO_PREFIX} Source ID Lead {idx}",
			"lead_name": f"{DEMO_PREFIX} Source ID Lead {idx}",
			"status": "New",
			"source": spec["source"],
			"sr_lead_pipeline": spec["pipeline"],
			"sr_w_source_id": spec["source_id"],
			"lead_temperature": spec["temperature"],
			"lead_score": spec["score"],
		}
	)
	lead.insert(ignore_permissions=True, ignore_mandatory=True)
	auto_assign_lead(lead.name, event_type="Manual Source ID Test")
	return {
		"lead": lead.name,
		"matched_rule": spec["rule"],
		"pipeline": spec["pipeline"],
		"source_id": spec["source_id"],
		"lead_owner": frappe.db.get_value("CRM Lead", lead.name, "lead_owner"),
		"source_after_assignment": frappe.db.get_value("CRM Lead", lead.name, "source"),
		"expected_owner": spec["expected_owner"],
		"expected_source": spec["expected_source"],
	}


def _create_whatsapp_dummy_lead(spec: dict, idx: int) -> dict:
	from new_assignement_system.engine.service import auto_assign_lead

	_ensure_named_master(frappe.get_meta("CRM Lead").get_field("source").options, spec["source"])
	lead = frappe.get_doc(
		{
			"doctype": "CRM Lead",
			"first_name": f"{DEMO_PREFIX} WhatsApp Dummy {idx}",
			"lead_name": f"{DEMO_PREFIX} WhatsApp Dummy {idx}",
			"status": "New",
			"source": spec["source"],
			"sr_lead_pipeline": spec["pipeline"],
			"sr_w_source_id": spec.get("source_id") or WHATSAPP_SOURCE_ID,
			"sr_w_source_url": spec.get("source_url") or WHATSAPP_SOURCE_URL,
			"sr_w_ctwa_clid": spec.get("ctwa_clid") or WHATSAPP_CTWA_CLID,
			"lead_temperature": spec["temperature"],
			"lead_score": spec["score"],
		}
	)
	lead.insert(ignore_permissions=True, ignore_mandatory=True)
	auto_assign_lead(lead.name, event_type="Manual WhatsApp Dummy Test")
	return {
		"lead": lead.name,
		"pipeline": spec["pipeline"],
		"sr_w_source_id": frappe.db.get_value("CRM Lead", lead.name, "sr_w_source_id"),
		"sr_w_source_url": frappe.db.get_value("CRM Lead", lead.name, "sr_w_source_url"),
		"sr_w_ctwa_clid": frappe.db.get_value("CRM Lead", lead.name, "sr_w_ctwa_clid"),
		"lead_owner": frappe.db.get_value("CRM Lead", lead.name, "lead_owner"),
		"source_after_assignment": frappe.db.get_value("CRM Lead", lead.name, "source"),
		"expected_owner": spec["expected_owner"],
		"expected_source": spec["expected_source"],
	}


def _ensure_sr_lead_pipeline(pipeline: str) -> None:
	if frappe.db.exists("SR Lead Pipeline", pipeline):
		return
	frappe.get_doc(
		{
			"doctype": "SR Lead Pipeline",
			"sr_pipeline_name": pipeline,
			"is_active": 1,
		}
	).insert(ignore_permissions=True)


def _ensure_users_and_sessions() -> None:
	for idx, email in enumerate(USERS, start=1):
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": f"NAS Demo Agent {idx}",
					"enabled": 1,
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		else:
			frappe.db.set_value("User", email, "enabled", 1)
		frappe.db.sql(
			"""
			insert into `tabSessions` (sid, user, sessiondata, status, lastupdate)
			values (%s, %s, %s, 'Active', %s)
			on duplicate key update status = 'Active', lastupdate = values(lastupdate)
			""",
			(f"nas-demo-{email}", email, "{}", now_datetime()),
		)
	for email, pipeline in zip(USERS, ["High Intent", "Nurture", "Paid Campaign", "Partner Referral"], strict=True):
		_ensure_user_permission(email, "SR Lead Pipeline", pipeline)


def _ensure_user_permission(user: str, allow: str, for_value: str) -> None:
	if frappe.db.exists("User Permission", {"user": user, "allow": allow, "for_value": for_value}):
		return
	frappe.get_doc(
		{
			"doctype": "User Permission",
			"user": user,
			"allow": allow,
			"for_value": for_value,
			"apply_to_all_doctypes": 1,
		}
	).insert(ignore_permissions=True)


def _enable_settings() -> None:
	settings = frappe.get_single("New Assignement System Settings")
	settings.update(
		{
			"enabled": 1,
			"queue_enabled": 0,
			"auto_assign_on_insert": 1,
			"inline_assign_on_insert": 1,
			"auto_reassign_on_update": 0,
			"auto_unassign_on_update": 1,
			"enable_metadata_based_assignment": 1,
			"allow_fallback_without_active_session": 0,
			"sync_todo": 1,
			"sync_docshare": 1,
			"default_strategy": "Balanced Load",
		}
	)
	settings.save(ignore_permissions=True)


def _disable_auto_crm_lead_assigner() -> None:
	if frappe.db.exists("DocType", "Auto CRM Assignment Settings"):
		settings = frappe.get_single("Auto CRM Assignment Settings")
		settings.enabled = 0
		settings.save(ignore_permissions=True)


def _delete_demo_rules() -> None:
	for name in frappe.get_all("New Assignement System Rule", filters={"rule_name": ["like", f"{DEMO_PREFIX}%"]}, pluck="name"):
		frappe.delete_doc("New Assignement System Rule", name, ignore_permissions=True, force=True)


def _create_rules() -> list[str]:
	specs = [
		{
			"rule_name": f"{DEMO_PREFIX} - Website Hot High Intent",
			"priority": 10,
			"source": "Auto Website",
			"pipeline": "High Intent",
			"score_min": 80,
			"user": USERS[0],
			"filters": [
				{"fieldname": "lead_temperature", "operator": "Equals", "value": "Hot"},
				{"fieldname": "lead_score", "operator": "Greater Than Or Equal", "value": "80"},
			],
		},
		{
			"rule_name": f"{DEMO_PREFIX} - Facebook Warm Nurture",
			"priority": 20,
			"source": "Auto Facebook",
			"pipeline": "Nurture",
			"score_min": 40,
			"score_max": 79,
			"user": USERS[1],
			"filters": [
				{"fieldname": "lead_temperature", "operator": "In", "value": "Warm,Hot"},
				{"fieldname": "lead_score", "operator": "Between", "value": "40", "value_to": "79"},
			],
		},
		{
			"rule_name": f"{DEMO_PREFIX} - Google Paid Campaign",
			"priority": 30,
			"source": "Auto Google Ads",
			"pipeline": "Paid Campaign",
			"score_min": 61,
			"user": USERS[2],
			"filters": [
				{"fieldname": "lead_temperature", "operator": "Not Equals", "value": "Cold"},
			],
		},
		{
			"rule_name": f"{DEMO_PREFIX} - Referral Partner",
			"priority": 40,
			"source": "Auto Referral",
			"pipeline": "Partner Referral",
			"score_min": 50,
			"user": USERS[3],
			"filters": [
				{"fieldname": "lead_temperature", "operator": "Is Set"},
			],
		},
	]

	created = []
	for spec in specs:
		rule = frappe.get_doc(
			{
				"doctype": "New Assignement System Rule",
				"rule_name": spec["rule_name"],
				"enabled": 1,
				"priority": spec["priority"],
				"strategy": "Balanced Load",
				"pipeline": spec["pipeline"],
				"source": spec["source"],
				"target_source": spec["source"],
				"status": "New",
				"lead_score_min": spec.get("score_min"),
				"lead_score_max": spec.get("score_max"),
				"only_if_unassigned": 1,
				"assign_to_users": [
					{
						"user": spec["user"],
						"enabled": 1,
						"weight": 1,
						"capacity": 0,
						"max_daily_assignments": 0,
					}
				],
				"metadata_filters": spec["filters"],
			}
		)
		rule.insert(ignore_permissions=True)
		created.append(rule.name)
	return created


def _lead_specs() -> list[dict]:
	return [
		{"source": "Auto Website", "pipeline": "High Intent", "temperature": "Hot", "score": 95},
		{"source": "Auto Website", "pipeline": "High Intent", "temperature": "Hot", "score": 88},
		{"source": "Auto Facebook", "pipeline": "Nurture", "temperature": "Warm", "score": 55},
		{"source": "Auto Facebook", "pipeline": "Nurture", "temperature": "Hot", "score": 70},
		{"source": "Auto Google Ads", "pipeline": "Paid Campaign", "temperature": "Warm", "score": 72},
		{"source": "Auto Google Ads", "pipeline": "Paid Campaign", "temperature": "Hot", "score": 81},
		{"source": "Auto Referral", "pipeline": "Partner Referral", "temperature": "Warm", "score": 65},
		{"source": "Auto Referral", "pipeline": "Partner Referral", "temperature": "Cold", "score": 52},
	]
