from __future__ import annotations

import frappe

from new_assignement_system.engine.queue import enqueue_lead

LEGACY_FRAPPE_ASSIGNMENT_RULES = (
	"MI Lead Rule-Aman",
	"Mi Lead Rule-karan",
	"Mi Lead Rule-mandeep",
	"Mi Lead Rule-ankit",
)


def _as_values(value) -> list[str]:
	if isinstance(value, str):
		try:
			parsed = frappe.parse_json(value)
			if isinstance(parsed, list):
				value = parsed
		except Exception:
			value = value.replace(",", "\n").splitlines()
	if not isinstance(value, list):
		return []
	return [str(item).strip() for item in value if str(item).strip()]


@frappe.whitelist()
def upsert_multi_campaign_rule(
	rule_name: str,
	campaigns,
	agents=None,
	team: str | None = None,
	priority: int = 10,
	strategy: str = "Balanced Load",
) -> dict:
	campaign_values = _as_values(campaigns)
	agent_values = _as_values(agents or [])

	if not rule_name:
		frappe.throw("Rule Name is required.")
	if not campaign_values:
		frappe.throw("At least one campaign value is required.")
	if team and not frappe.db.exists("Team", team):
		frappe.throw(f"Team {team} does not exist.")

	for agent in agent_values:
		if not frappe.db.exists("User", {"name": agent, "enabled": 1}):
			frappe.throw(f"Invalid or disabled agent: {agent}")

	name = frappe.db.exists("New Assignement System Rule", rule_name)
	if name:
		doc = frappe.get_doc("New Assignement System Rule", name)
	else:
		doc = frappe.new_doc("New Assignement System Rule")
		doc.rule_name = rule_name

	doc.enabled = 1
	doc.priority = int(priority or 10)
	doc.strategy = strategy or "Balanced Load"
	doc.team = team
	doc.campaign = campaign_values[0]
	doc.campaign_values = "\n".join(campaign_values)
	doc.target_agents = "\n".join(agent_values)
	doc.only_if_unassigned = 1
	doc.save(ignore_permissions=True)

	return {
		"status": "ok",
		"name": doc.name,
		"campaign_count": len(campaign_values),
		"agent_count": len(agent_values),
	}


@frappe.whitelist()
def upsert_source_id_rule(
	rule_name: str,
	pipeline: str,
	source_id: str,
	agent: str,
	team: str | None = None,
	priority: int = 5,
	strategy: str = "Balanced Load",
) -> dict:
	if not rule_name:
		frappe.throw("Rule Name is required.")
	if not pipeline:
		frappe.throw("Pipeline is required.")
	if not source_id:
		frappe.throw("Source ID is required.")
	if not agent:
		frappe.throw("Agent is required.")
	if team and not frappe.db.exists("Team", team):
		frappe.throw(f"Team {team} does not exist.")
	if not frappe.db.exists("User", {"name": agent, "enabled": 1}):
		frappe.throw(f"Invalid or disabled agent: {agent}")

	from new_assignement_system.engine.counters import ensure_agent_state
	from new_assignement_system.integrations.role_permissions import agent_allowed_for_pipeline

	ensure_agent_state(agent, team)
	if not agent_allowed_for_pipeline(agent, pipeline):
		frappe.throw(
			frappe._("Agent <b>{0}</b> is not allowed for pipeline <b>{1}</b>.").format(agent, pipeline),
			title="Pipeline Permission Missing",
		)

	name = frappe.db.exists("New Assignement System Rule", rule_name)
	if name:
		doc = frappe.get_doc("New Assignement System Rule", name)
	else:
		doc = frappe.new_doc("New Assignement System Rule")
		doc.rule_name = rule_name

	doc.enabled = 1
	doc.priority = int(priority or 5)
	doc.strategy = strategy or "Balanced Load"
	doc.team = team
	doc.target_agents = agent
	doc.pipeline = pipeline
	doc.source_id_values = source_id
	doc.only_if_unassigned = 1
	doc.fallback_user = agent
	doc.save(ignore_permissions=True)

	return {"status": "ok", "name": doc.name, "pipeline": pipeline, "source_id_values": source_id, "agent": agent}


@frappe.whitelist()
def ensure_pipeline_user_permissions(users, pipeline: str, pipeline_doctype: str = "SR Lead Pipeline") -> dict:
	user_values = _as_values(users)
	if not user_values:
		frappe.throw("At least one user is required.")
	if not pipeline:
		frappe.throw("Pipeline is required.")
	if not frappe.db.exists("DocType", pipeline_doctype):
		frappe.throw(f"DocType {pipeline_doctype} does not exist.")
	if not frappe.db.exists(pipeline_doctype, pipeline):
		frappe.throw(f"{pipeline_doctype} {pipeline} does not exist.")

	created = []
	existing = []
	for user in user_values:
		if not frappe.db.exists("User", {"name": user, "enabled": 1}):
			frappe.throw(f"Invalid or disabled user: {user}")
		name = frappe.db.exists(
			"User Permission",
			{
				"user": user,
				"allow": pipeline_doctype,
				"for_value": pipeline,
			},
		)
		if name:
			existing.append(name)
			continue

		doc = frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": pipeline_doctype,
				"for_value": pipeline,
				"apply_to_all_doctypes": 1,
			}
		)
		doc.insert(ignore_permissions=True)
		created.append(doc.name)

	frappe.clear_cache()
	return {"status": "ok", "created": created, "existing": existing}


@frappe.whitelist()
def disable_legacy_frappe_assignment_rules(rule_names=None) -> dict:
	disabled = []
	missing = []
	already_disabled = []

	for rule_name in _as_values(rule_names) or list(LEGACY_FRAPPE_ASSIGNMENT_RULES):
		if not frappe.db.exists("Assignment Rule", rule_name):
			missing.append(rule_name)
			continue

		is_disabled = frappe.db.get_value("Assignment Rule", rule_name, "disabled")
		if is_disabled:
			already_disabled.append(rule_name)
			continue

		frappe.db.set_value("Assignment Rule", rule_name, "disabled", 1)
		disabled.append(rule_name)

	frappe.clear_cache()
	return {"status": "ok", "disabled": disabled, "already_disabled": already_disabled, "missing": missing}


@frappe.whitelist()
def enqueue_campaign_leads(campaigns, only_unassigned: int = 1, limit: int = 0) -> dict:
	campaign_values = _as_values(campaigns)
	if not campaign_values:
		frappe.throw("At least one campaign value is required.")

	fields = _campaign_fields()
	if not fields:
		return {"status": "skipped", "reason": "No campaign fields found on CRM Lead", "queued": 0}

	conditions = [f"`{field}` in %(campaigns)s" for field in fields]
	where = [f"({' or '.join(conditions)})"]
	if int(only_unassigned):
		where.append("(`lead_owner` is null or `lead_owner` = '')")
	if frappe.db.has_column("CRM Lead", "converted"):
		where.append("ifnull(`converted`, 0) = 0")
	if frappe.db.has_column("CRM Lead", "sr_is_archived"):
		where.append("ifnull(`sr_is_archived`, 0) = 0")
	if frappe.db.has_column("CRM Lead", "sr_is_duplicate"):
		where.append("ifnull(`sr_is_duplicate`, 0) = 0")

	limit_clause = f" limit {int(limit)}" if int(limit or 0) > 0 else ""
	rows = frappe.db.sql(
		f"""
		select name
		from `tabCRM Lead`
		where {" and ".join(where)}
		order by creation asc
		{limit_clause}
		""",
		{"campaigns": tuple(campaign_values)},
		as_dict=True,
	)

	queued = 0
	for row in rows:
		if enqueue_lead(row.name, event_type="Bulk", priority=10, process_now=False):
			queued += 1

	return {"status": "ok", "matched": len(rows), "queued": queued}


@frappe.whitelist()
def process_queued_campaign_leads(campaigns, limit: int = 500) -> dict:
	campaign_values = _as_values(campaigns)
	if not campaign_values:
		frappe.throw("At least one campaign value is required.")

	fields = _campaign_fields()
	if not fields:
		return {"status": "skipped", "reason": "No campaign fields found on CRM Lead", "processed": 0}

	conditions = [f"l.`{field}` in %(campaigns)s" for field in fields]
	limit_clause = f" limit {int(limit)}" if int(limit or 0) > 0 else ""
	rows = frappe.db.sql(
		f"""
		select q.name
		from `tabNew Assignement System Queue` q
		inner join `tabCRM Lead` l on l.name = q.lead
		where q.status in ('Pending', 'Retry')
		  and ({' or '.join(conditions)})
		order by q.priority asc, q.creation asc
		{limit_clause}
		""",
		{"campaigns": tuple(campaign_values)},
		as_dict=True,
	)

	from new_assignement_system.jobs import process_assignment_queue_item

	processed = 0
	for row in rows:
		process_assignment_queue_item(row.name)
		processed += 1

	return {"status": "ok", "matched": len(rows), "processed": processed}


def _campaign_fields() -> list[str]:
	candidates = (
		"campaign",
		"utm_campaign",
		"sr_campaign",
		"sr_utm_campaign_id",
		"sr_f_campaign_id",
		"sr_utm_campaign",
		"sr_f_campaign_name",
		"sr_w_campaign_name",
		"sr_w_source_id",
	)
	return [field for field in candidates if frappe.db.has_column("CRM Lead", field)]
