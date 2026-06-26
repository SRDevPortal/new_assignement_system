from __future__ import annotations

import frappe

from new_assignement_system.engine.context import get_campaign, get_disposition, get_pipeline


def select_agent(candidates: list[frappe._dict], strategy: str | None, lead: dict) -> frappe._dict | None:
	if not candidates:
		return None

	strategy = strategy or "Balanced Load"
	if strategy == "Round Robin":
		return _round_robin(candidates)
	if strategy == "Weighted Balanced":
		return _weighted_balanced(candidates)
	if strategy == "Skill Based":
		return _skill_based(candidates, lead)
	return _balanced(candidates)


def _round_robin(candidates: list[frappe._dict]) -> frappe._dict:
	return sorted(candidates, key=lambda row: (_last_assigned_key(row), row.current_open_leads or 0, row.agent))[0]


def _balanced(candidates: list[frappe._dict]) -> frappe._dict:
	return sorted(
		candidates,
		key=lambda row: (row.current_open_leads or 0, _last_assigned_key(row), row.agent),
	)[0]


def _weighted_balanced(candidates: list[frappe._dict]) -> frappe._dict:
	return sorted(
		candidates,
		key=lambda row: (_load_ratio(row), _last_assigned_key(row), row.agent),
	)[0]


def _last_assigned_key(row: frappe._dict) -> str:
	value = row.get("last_assigned_at")
	if not value:
		return ""
	if hasattr(value, "isoformat"):
		return value.isoformat()
	return str(value)


def _skill_based(candidates: list[frappe._dict], lead: dict) -> frappe._dict:
	tags = {
		str(value).strip().lower()
		for value in (
			get_pipeline(lead),
			lead.get("source"),
			get_campaign(lead),
			get_disposition(lead),
			lead.get("lead_temperature"),
			lead.get("status"),
		)
		if value
	}
	matched = [row for row in candidates if _row_tags(row) & tags]
	return _weighted_balanced(matched or candidates)


def _row_tags(row: frappe._dict) -> set[str]:
	raw = row.get("skill_tags")
	if not raw:
		return set()
	return {part.strip().lower() for part in str(raw).replace(",", "\n").splitlines() if part.strip()}


def _load_ratio(row: frappe._dict) -> float:
	weight = float(row.weight or 1)
	capacity = float(row.capacity or 0)
	open_leads = float(row.current_open_leads or 0)
	if capacity <= 0:
		return open_leads / weight
	return open_leads / (capacity * weight)
