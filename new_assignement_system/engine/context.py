from __future__ import annotations

import hashlib
import json
from typing import Iterable

import frappe

LEAD_DOCTYPE = "CRM Lead"

BASE_FIELDS = (
	"name",
	"lead_owner",
	"status",
	"source",
	"converted",
	"creation",
	"modified",
)

OPTIONAL_FIELDS = (
	"team",
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
	"sr_is_archived",
	"sr_is_duplicate",
	"sr_duplicate_of_name",
	"sr_duplicate_of",
	"sr_dedupe_status",
	"sr_dedupe_stage",
	"sr_dedupe_result",
	"sr_dedupe_not_before",
	"sr_assignment_stage",
	"sr_assignment_next_attempt_at",
	"mobile_no",
)


def has_lead_field(fieldname: str) -> bool:
	try:
		return bool(frappe.db.has_column(LEAD_DOCTYPE, fieldname))
	except Exception:
		return False


def lead_fields(extra: Iterable[str] | None = None) -> list[str]:
	fields = [field for field in BASE_FIELDS if field == "name" or has_lead_field(field)]
	for field in [*OPTIONAL_FIELDS, *(extra or [])]:
		if field not in fields and has_lead_field(field):
			fields.append(field)
	return fields


def get_lead_context(lead: str, *, for_update: bool = False, extra: Iterable[str] | None = None) -> frappe._dict:
	fields = lead_fields(extra)
	columns = ", ".join(f"`{field}`" for field in fields)
	lock = " for update" if for_update else ""
	rows = frappe.db.sql(
		f"select {columns} from `tabCRM Lead` where name=%s{lock}",
		lead,
		as_dict=True,
	)
	if not rows:
		frappe.throw(f"CRM Lead {lead} does not exist.", frappe.DoesNotExistError)
	return frappe._dict(rows[0])


def first_value(row: dict, fieldnames: Iterable[str]):
	for fieldname in fieldnames:
		value = row.get(fieldname)
		if value not in (None, ""):
			return value
	return None


def get_pipeline(row: dict):
	return first_value(row, ("sr_lead_pipeline", "pipeline"))


def get_source_id(row: dict):
	return first_value(row, ("sr_w_source_id",))


def get_campaign(row: dict):
	return first_value(
		row,
		(
			"campaign",
			"utm_campaign",
			"sr_campaign",
			"sr_utm_campaign_id",
			"sr_f_campaign_id",
			"sr_utm_campaign",
			"sr_f_campaign_name",
			"sr_w_campaign_name",
		),
	)


def get_disposition(row: dict):
	return first_value(row, ("sr_lead_disposition", "disposition"))


def get_lead_score(row: dict):
	value = row.get("lead_score")
	if value in (None, ""):
		return None
	try:
		return float(value)
	except Exception:
		return None


def snapshot(row: dict) -> dict:
	return {
		"name": row.get("name"),
		"lead_owner": row.get("lead_owner"),
		"team": row.get("team"),
		"status": row.get("status"),
		"source": row.get("source"),
		"pipeline": get_pipeline(row),
		"source_id": get_source_id(row),
		"campaign": get_campaign(row),
		"disposition": get_disposition(row),
		"lead_score": get_lead_score(row),
		"converted": row.get("converted"),
	}


def snapshot_json(row: dict) -> str:
	return frappe.as_json(snapshot(row))


def snapshot_hash(row: dict) -> str:
	payload = json.dumps(snapshot(row), sort_keys=True, default=str)
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()
