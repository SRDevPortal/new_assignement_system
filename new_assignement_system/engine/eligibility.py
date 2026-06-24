from __future__ import annotations

from datetime import datetime, time

import frappe
from frappe.sessions import get_expired_threshold
from frappe.utils import get_time, now_datetime

from new_assignement_system.engine.context import get_campaign, get_pipeline
from new_assignement_system.integrations.role_permissions import agent_allowed_for_pipeline
from new_assignement_system.integrations.team import get_active_team_members


def get_candidate_agents(rule: frappe._dict | None, lead: dict) -> list[frappe._dict]:
	return _get_rule_user_candidates(rule, lead)


def is_user_session_available(user: str | None) -> bool:
	if not user:
		return False
	if not frappe.db.exists("User", {"name": user, "enabled": 1}):
		return False

	return bool(
		frappe.db.sql(
			"""
			select sid
			from `tabSessions`
			where user = %s
			  and status = 'Active'
			  and lastupdate >= %s
			limit 1
			""",
			(user, get_expired_threshold()),
		)
	)


def _get_rule_user_candidates(rule: frappe._dict | None, lead: dict) -> list[frappe._dict]:
	if not rule:
		return []

	if not _has_rule_users(rule) and rule.get("team"):
		return _get_team_user_candidates(rule, lead)
	if not _has_rule_users(rule):
		return []

	rows = frappe.db.sql(
		"""
		select
			ru.name,
			ru.user as agent,
			coalesce(nullif(ru.weight, 0), nullif(s.weight, 0), 1) as weight,
			coalesce(nullif(ru.capacity, 0), nullif(s.capacity, 0), 0) as capacity,
			coalesce(s.current_open_leads, 0) as current_open_leads,
			coalesce(s.today_assigned_count, 0) as today_assigned_count,
			coalesce(s.today_reassigned_count, 0) as today_reassigned_count,
			s.last_assigned_at,
			coalesce(s.load_score, 0) as load_score,
			s.allowed_pipelines,
			s.allowed_sources,
			s.allowed_campaigns,
			s.skill_tags,
			s.shift_start,
			s.shift_end,
			coalesce(ru.max_daily_assignments, 0) as max_daily_assignments
		from `tabNew Assignement System Rule User` ru
		inner join `tabUser` u on u.name = ru.user and ifnull(u.enabled, 0) = 1
		left join `tabNew Assignement System Agent State` s
			on s.agent = ru.user
		where ru.parent = %(rule)s
		  and ru.parenttype = 'New Assignement System Rule'
		  and ru.parentfield = 'assign_to_users'
		  and ifnull(ru.enabled, 1) = 1
		  and ru.user is not null
		  and ru.user != ''
		order by load_score asc, last_assigned_at asc, ru.idx asc
		""",
		{"rule": rule.name},
		as_dict=True,
	)

	if rule.get("team"):
		members = set(get_active_team_members(rule.get("team")))
		rows = [row for row in rows if row.agent in members]

	return [frappe._dict(row) for row in rows if _is_eligible(row, rule, lead)]


def _get_team_user_candidates(rule: frappe._dict, lead: dict) -> list[frappe._dict]:
	members = get_active_team_members(rule.get("team"))
	if not members:
		return []

	rows = frappe.db.sql(
		"""
		select
			u.name as name,
			u.name as agent,
			coalesce(nullif(s.weight, 0), 1) as weight,
			coalesce(s.capacity, 0) as capacity,
			coalesce(s.current_open_leads, 0) as current_open_leads,
			coalesce(s.today_assigned_count, 0) as today_assigned_count,
			coalesce(s.today_reassigned_count, 0) as today_reassigned_count,
			s.last_assigned_at,
			coalesce(s.load_score, 0) as load_score,
			s.allowed_pipelines,
			s.allowed_sources,
			s.allowed_campaigns,
			s.skill_tags,
			s.shift_start,
			s.shift_end,
			0 as max_daily_assignments
		from `tabUser` u
		left join `tabNew Assignement System Agent State` s
			on s.agent = u.name
		where u.name in %(members)s
		  and ifnull(u.enabled, 0) = 1
		order by load_score asc, last_assigned_at asc, u.name asc
		""",
		{"members": tuple(members)},
		as_dict=True,
	)

	return [frappe._dict(row) for row in rows if _is_eligible(row, rule, lead)]


def _has_rule_users(rule: frappe._dict | None) -> bool:
	if not rule or not frappe.db.exists("DocType", "New Assignement System Rule User"):
		return False
	return bool(
		frappe.db.exists(
			"New Assignement System Rule User",
			{
				"parent": rule.name,
				"parenttype": "New Assignement System Rule",
				"parentfield": "assign_to_users",
				"enabled": 1,
			},
		)
	)


def _is_eligible(row: dict, rule: frappe._dict | None, lead: dict) -> bool:
	if not is_user_session_available(row.get("agent")):
		return False

	capacity = int(row.get("capacity") or 0)
	rule_cap = int((rule or {}).get("max_open_leads_per_agent") or 0)
	effective_capacity = min([value for value in (capacity, rule_cap) if value] or [0])
	if effective_capacity and int(row.get("current_open_leads") or 0) >= effective_capacity:
		return False
	max_daily = int(row.get("max_daily_assignments") or 0)
	if max_daily and int(row.get("today_assigned_count") or 0) >= max_daily:
		return False

	pipeline = get_pipeline(lead)
	if not _allowed_by_list(row.get("allowed_pipelines"), pipeline):
		return False
	if not agent_allowed_for_pipeline(row.get("agent"), pipeline):
		return False
	if not _allowed_by_list(row.get("allowed_sources"), lead.get("source")):
		return False
	if not _allowed_by_list(row.get("allowed_campaigns"), get_campaign(lead)):
		return False
	if not _inside_shift(row.get("shift_start"), row.get("shift_end")):
		return False
	return True


def _allowed_by_list(raw: str | None, value: str | None) -> bool:
	values = _split_values(raw)
	if not values:
		return True
	if value in (None, ""):
		return False
	return str(value).strip() in values


def _split_values(raw: str | None) -> set[str]:
	if not raw:
		return set()
	return {part.strip() for part in str(raw).replace(",", "\n").splitlines() if part.strip()}


def _inside_shift(start_value, end_value) -> bool:
	if not start_value or not end_value:
		return True

	start = _to_time(start_value)
	end = _to_time(end_value)
	current = now_datetime().time()

	if not start or not end:
		return True
	if _seconds_between(start, end) < 60:
		return True
	if start <= end:
		return start <= current <= end
	return current >= start or current <= end


def _to_time(value) -> time | None:
	if isinstance(value, time):
		return value
	if isinstance(value, datetime):
		return value.time()
	try:
		return get_time(value)
	except Exception:
		return None


def _seconds_between(start: time, end: time) -> int:
	start_seconds = start.hour * 3600 + start.minute * 60 + start.second
	end_seconds = end.hour * 3600 + end.minute * 60 + end.second
	return abs(end_seconds - start_seconds)
