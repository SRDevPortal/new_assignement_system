from __future__ import annotations

import frappe
from frappe.utils import cint, get_datetime, now_datetime

from new_assignement_system.engine.context import (
	get_campaign,
	get_disposition,
	get_lead_score,
	get_pipeline,
	get_source_id,
)
from new_assignement_system.settings import get_settings

FILTER_MATCH_ALL = "Match All Configured Filters"
FILTER_MATCH_ANY = "Match Any Configured Filter"

REASSIGNMENT_FIELD_MAP = {
	"lead_status": "status",
	"pipeline": "sr_lead_pipeline",
	"source_id": "sr_w_source_id",
	"lead_owner": "lead_owner",
}


def match_rule(lead: dict, *, event_type: str | None = None) -> frappe._dict | None:
	fields = _rule_fields(
		[
			"name",
			"rule_name",
			"priority",
			"strategy",
			"team",
			"target_source",
			"target_pipeline",
			"filter_match_mode",
			"pipeline",
			"source_id_values",
			"source",
			"campaign",
			"campaign_values",
			"status",
			"disposition",
			"lead_score_min",
			"lead_score_max",
			"only_if_unassigned",
			"max_open_leads_per_agent",
			"reassign_after_minutes",
			"fallback_user",
			"metadata_filters_json",
			"unassign_enabled",
			"unassign_condition",
		]
	)

	rules = frappe.get_all(
		"New Assignement System Rule",
		filters={"enabled": 1},
		fields=fields,
		order_by="priority asc, modified asc",
		limit_page_length=0,
	)

	for rule in rules:
		rule = frappe._dict(rule)
		if _matches_rule(rule, lead, event_type=event_type):
			target_values = get_reassignment_target_values(rule.name, lead)
			if target_values is None:
				continue
			rule.reassignment_target_values = target_values
			return rule
	return None


def match_unassign_rule(lead: dict, *, event_type: str | None = None) -> frappe._dict | None:
	fields = _rule_fields(
		[
			"name",
			"rule_name",
			"priority",
			"strategy",
			"target_source",
			"target_pipeline",
			"unassign_enabled",
			"unassign_condition",
			"metadata_filters_json",
		]
	)

	rules = frappe.get_all(
		"New Assignement System Rule",
		filters={"enabled": 1, "unassign_enabled": 1},
		fields=fields,
		order_by="priority asc, modified asc",
		limit_page_length=0,
	)

	for rule in rules:
		rule = frappe._dict(rule)
		if _matches_unassign_rule(rule, lead, event_type=event_type):
			return rule
	return None


def _rule_fields(fieldnames: list[str]) -> list[str]:
	available = []
	for fieldname in fieldnames:
		if fieldname == "name" or frappe.db.has_column("New Assignement System Rule", fieldname):
			available.append(fieldname)
	return available


def _matches_rule(rule: frappe._dict, lead: dict, *, event_type: str | None = None) -> bool:
	if (
		cint(rule.only_if_unassigned)
		and lead.get("lead_owner")
		and event_type not in {"Reassign", "Stale"}
		and not has_reassignment_match_rows(rule.name)
	):
		return False

	filter_results = []

	_add_filter_result(filter_results, rule.pipeline, _matches_any(rule.pipeline, get_pipeline(lead)))
	_add_filter_result(filter_results, rule.source_id_values, _matches_any(rule.source_id_values, get_source_id(lead)))
	_add_filter_result(filter_results, rule.source, _matches_any(rule.source, lead.get("source")))
	_add_filter_result(
		filter_results,
		rule.campaign_values or rule.campaign,
		_matches_any(rule.campaign_values or rule.campaign, get_campaign(lead)),
	)
	_add_filter_result(filter_results, rule.status, _matches_any(rule.status, lead.get("status")))
	_add_filter_result(filter_results, rule.disposition, _matches_any(rule.disposition, get_disposition(lead)))

	score = get_lead_score(lead)
	if _has_bound(rule.lead_score_min) or _has_bound(rule.lead_score_max):
		filter_results.append(_matches_score_bounds(rule, score))

	settings = get_settings()
	if cint(settings.enable_metadata_based_assignment):
		metadata_filters = get_metadata_filters(rule.name)
		if metadata_filters:
			if _is_match_any(rule):
				filter_results.append(matches_any_metadata_filter(metadata_filters, lead))
			else:
				filter_results.append(matches_metadata_filters(metadata_filters, lead))
		if rule.get("metadata_filters_json"):
			if _is_match_any(rule):
				filter_results.append(_matches_any_metadata(rule.get("metadata_filters_json"), lead))
			else:
				filter_results.append(_matches_metadata(rule.get("metadata_filters_json"), lead))

	if not filter_results:
		return True
	return any(filter_results) if _is_match_any(rule) else all(filter_results)


def get_reassignment_target_values(rule_name: str | None, lead: dict) -> dict | None:
	if not rule_name or not frappe.db.exists("DocType", "New Assignement System Reassignment Match"):
		return {}

	match_rows = frappe.get_all(
		"New Assignement System Reassignment Match",
		filters={
			"parent": rule_name,
			"parenttype": "New Assignement System Rule",
			"parentfield": "reassignment_existing_values",
			"enabled": 1,
		},
		fields=[
			"idx",
			"lead_status",
			"pipeline",
			"source_id",
			"stale_time_days",
			"lead_owner",
		],
		order_by="idx asc",
		limit_page_length=0,
	)
	if not match_rows:
		return {}

	for row in match_rows:
		row = frappe._dict(row)
		if not _matches_reassignment_row(row, lead):
			continue
		target = _get_reassignment_target_row(rule_name, row.idx)
		if target:
			return _target_row_to_updates(target)
		return {}
	return None


def has_reassignment_match_rows(rule_name: str | None) -> bool:
	if not rule_name or not frappe.db.exists("DocType", "New Assignement System Reassignment Match"):
		return False
	return bool(
		frappe.db.exists(
			"New Assignement System Reassignment Match",
			{
				"parent": rule_name,
				"parenttype": "New Assignement System Rule",
				"parentfield": "reassignment_existing_values",
				"enabled": 1,
			},
		)
	)


def _matches_reassignment_row(row: frappe._dict, lead: dict) -> bool:
	return (
		_matches_optional(row.lead_status, lead.get("status"))
		and _matches_optional(row.pipeline, get_pipeline(lead))
		and _matches_optional(row.source_id, get_source_id(lead))
		and _matches_stale_days(row.stale_time_days, lead.get("creation"))
		and _matches_optional(row.lead_owner, lead.get("lead_owner"))
	)


def _get_reassignment_target_row(rule_name: str, idx: int) -> frappe._dict | None:
	if not frappe.db.exists("DocType", "New Assignement System Reassignment Target"):
		return None

	rows = frappe.get_all(
		"New Assignement System Reassignment Target",
		filters={
			"parent": rule_name,
			"parenttype": "New Assignement System Rule",
			"parentfield": "reassignment_new_values",
			"enabled": 1,
			"idx": idx,
		},
		fields=[
			"lead_status",
			"pipeline",
			"source_id",
			"lead_owner",
		],
		limit_page_length=1,
	)
	if rows:
		return frappe._dict(rows[0])

	rows = frappe.get_all(
		"New Assignement System Reassignment Target",
		filters={
			"parent": rule_name,
			"parenttype": "New Assignement System Rule",
			"parentfield": "reassignment_new_values",
			"enabled": 1,
		},
		fields=[
			"lead_status",
			"pipeline",
			"source_id",
			"lead_owner",
		],
		order_by="idx asc",
		limit_page_length=1,
	)
	return frappe._dict(rows[0]) if rows else None


def _target_row_to_updates(row: frappe._dict) -> dict:
	updates = {}
	for source_field, lead_field in REASSIGNMENT_FIELD_MAP.items():
		value = row.get(source_field)
		if value not in (None, ""):
			updates[lead_field] = value
	return updates


def _is_match_any(rule: frappe._dict) -> bool:
	return (rule.get("filter_match_mode") or FILTER_MATCH_ALL) == FILTER_MATCH_ANY


def _add_filter_result(results: list[bool], configured_value, matched: bool) -> None:
	if _split_values(configured_value):
		results.append(matched)


def _matches_score_bounds(rule: frappe._dict, score) -> bool:
	if score is None:
		return False
	if _has_bound(rule.lead_score_min) and score < float(rule.lead_score_min):
		return False
	if _has_bound(rule.lead_score_max) and score > float(rule.lead_score_max):
		return False
	return True


def _matches_unassign_rule(rule: frappe._dict, lead: dict, *, event_type: str | None = None) -> bool:
	settings = get_settings()
	matched = False

	unassign_filters = get_metadata_filters(rule.name, parentfield="unassign_metadata_filters")
	if (
		cint(settings.enable_metadata_based_assignment)
		and unassign_filters
		and matches_metadata_filters(unassign_filters, lead)
	):
		matched = True

	if rule.get("unassign_condition"):
		try:
			if frappe.safe_eval(rule.get("unassign_condition"), None, frappe._dict(lead)):
				matched = True
		except Exception as exc:
			frappe.msgprint(
				frappe._("CRM Lead unassign condition failed for rule {0}: {1}").format(
					rule.get("name"), exc
				),
				indicator="orange",
			)

	return matched


def _matches(expected, actual) -> bool:
	if expected in (None, ""):
		return True
	return str(expected).strip() == str(actual or "").strip()


def _matches_optional(expected, actual) -> bool:
	if expected in (None, ""):
		return True
	return str(expected).strip() == str(actual or "").strip()


def _matches_stale_days(expected_days, creation) -> bool:
	if expected_days in (None, "", 0, 0.0):
		return True
	if not creation:
		return False
	try:
		days = float(expected_days)
		created_at = get_datetime(creation)
	except Exception:
		return False
	if days <= 0:
		return True
	age_seconds = (now_datetime() - created_at).total_seconds()
	return age_seconds >= days * 24 * 60 * 60


def _has_bound(value) -> bool:
	return value not in (None, "", 0, 0.0)


def _matches_any(expected, actual) -> bool:
	values = _split_values(expected)
	if not values:
		return True
	return str(actual or "").strip() in values


def _split_values(raw) -> set[str]:
	if raw in (None, ""):
		return set()
	if isinstance(raw, list | tuple | set):
		return {str(value).strip() for value in raw if str(value).strip()}
	return {part.strip() for part in str(raw).replace(",", "\n").splitlines() if part.strip()}


def _matches_metadata(metadata_filters_json: str | None, lead: dict) -> bool:
	if not metadata_filters_json:
		return True

	filters = frappe.parse_json(metadata_filters_json)
	if not isinstance(filters, dict):
		return True

	for fieldname, expected in filters.items():
		if isinstance(expected, list | tuple | set):
			if _lead_value(lead, fieldname) not in expected:
				return False
		elif not _matches_any(expected, _lead_value(lead, fieldname)):
			return False
	return True


def get_metadata_filters(
	rule_name: str | None,
	*,
	parentfield: str = "metadata_filters",
) -> list[frappe._dict]:
	if not rule_name or not frappe.db.exists("DocType", "New Assignement System Metadata Filter"):
		return []

	return frappe.get_all(
		"New Assignement System Metadata Filter",
		filters={
			"parent": rule_name,
			"parenttype": "New Assignement System Rule",
			"parentfield": parentfield,
			"enabled": 1,
		},
		fields=["fieldname", "operator", "value", "value_to"],
		order_by="idx asc",
		limit_page_length=0,
	)


def matches_metadata_filters(filters: list[dict], lead: dict) -> bool:
	for row in filters:
		if not _matches_metadata_filter(frappe._dict(row), lead):
			return False
	return True


def matches_any_metadata_filter(filters: list[dict], lead: dict) -> bool:
	for row in filters:
		if _matches_metadata_filter(frappe._dict(row), lead):
			return True
	return False


def _matches_any_metadata(metadata_filters_json: str | None, lead: dict) -> bool:
	if not metadata_filters_json:
		return False

	filters = frappe.parse_json(metadata_filters_json)
	if not isinstance(filters, dict):
		return False

	for fieldname, expected in filters.items():
		if isinstance(expected, list | tuple | set):
			if _lead_value(lead, fieldname) in expected:
				return True
		elif _matches_any(expected, _lead_value(lead, fieldname)):
			return True
	return False


def _matches_metadata_filter(row: frappe._dict, lead: dict) -> bool:
	operator = row.operator or "Equals"
	actual = _lead_value(lead, row.fieldname)

	if operator == "Is Set":
		return actual not in (None, "")
	if operator == "Is Not Set":
		return actual in (None, "")
	if operator == "Equals":
		return _compare_text(actual, row.value)
	if operator == "Not Equals":
		return not _compare_text(actual, row.value)
	if operator == "In":
		return str(actual or "").strip() in _split_values(row.value)
	if operator == "Not In":
		return str(actual or "").strip() not in _split_values(row.value)
	if operator == "Greater Than":
		return _compare_number(actual, row.value, ">")
	if operator == "Less Than":
		return _compare_number(actual, row.value, "<")
	if operator == "Greater Than Or Equal":
		return _compare_number(actual, row.value, ">=")
	if operator == "Less Than Or Equal":
		return _compare_number(actual, row.value, "<=")
	if operator == "Between":
		return _between(actual, row.value, row.value_to)
	return _compare_text(actual, row.value)


def _lead_value(lead: dict, fieldname: str):
	if fieldname in lead:
		return lead.get(fieldname)
	lead_name = lead.get("name")
	if not lead_name:
		return None
	try:
		if frappe.db.has_column("CRM Lead", fieldname):
			return frappe.db.get_value("CRM Lead", lead_name, fieldname)
	except Exception:
		return None
	return None


def _compare_text(actual, expected) -> bool:
	return str(actual or "").strip() == str(expected or "").strip()


def _compare_number(actual, expected, operator: str) -> bool:
	try:
		left = float(actual)
		right = float(expected)
	except Exception:
		return False
	if operator == ">":
		return left > right
	if operator == "<":
		return left < right
	if operator == ">=":
		return left >= right
	if operator == "<=":
		return left <= right
	return False


def _between(actual, start, end) -> bool:
	try:
		value = float(actual)
		lower = float(start)
		upper = float(end)
	except Exception:
		return False
	if lower > upper:
		lower, upper = upper, lower
	return lower <= value <= upper
