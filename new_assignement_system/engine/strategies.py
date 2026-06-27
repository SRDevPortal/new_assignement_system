from __future__ import annotations

import frappe

from new_assignement_system.engine.context import get_campaign, get_disposition, get_pipeline


def select_agent(
	candidates: list[frappe._dict],
	strategy: str | None,
	lead: dict,
	*,
	rule: frappe._dict | None = None,
) -> frappe._dict | None:
	if not candidates:
		return None

	strategy = strategy or "Balanced Load"
	if strategy == "Round Robin":
		return _round_robin(candidates, (rule or {}).get("name"))
	if strategy == "Weighted Balanced":
		return _weighted_balanced(candidates)
	if strategy == "Skill Based":
		return _skill_based(candidates, lead)
	return _balanced(candidates)


def _round_robin(candidates: list[frappe._dict], rule: str | None = None) -> frappe._dict:
	_apply_rule_last_assigned(candidates, rule)
	return sorted(
		candidates,
		key=lambda row: (
			_last_assigned_key(row, "rule_last_assigned_at"),
			row.current_open_leads or 0,
			row.get("rule_user_idx") or 0,
			row.agent,
		),
	)[0]


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


def _last_assigned_key(row: frappe._dict, fieldname: str = "last_assigned_at") -> str:
	value = row.get(fieldname)
	if not value:
		return ""
	if hasattr(value, "isoformat"):
		return value.isoformat()
	return str(value)


def _apply_rule_last_assigned(candidates: list[frappe._dict], rule: str | None) -> None:
	if not rule or not frappe.db.exists("DocType", "New Assignement System Log"):
		for row in candidates:
			row.rule_last_assigned_at = row.get("last_assigned_at")
		return

	agents = [row.agent for row in candidates if row.get("agent")]
	if not agents:
		return

	rows = frappe.db.sql(
		"""
		select new_owner, max(creation) as last_assigned_at
		from `tabNew Assignement System Log`
		where rule = %(rule)s
		  and new_owner in %(agents)s
		  and action in ('Assigned', 'Reassigned')
		  and status = 'Success'
		group by new_owner
		""",
		{"rule": rule, "agents": tuple(agents)},
		as_dict=True,
	)
	last_by_agent = {row.new_owner: row.last_assigned_at for row in rows}
	for row in candidates:
		row.rule_last_assigned_at = last_by_agent.get(row.agent)


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
