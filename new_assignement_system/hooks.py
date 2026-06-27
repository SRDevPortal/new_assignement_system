app_name = "new_assignement_system"
app_title = "New Assignement System"
app_publisher = "SRIAAS"
app_description = "Session-based CRM Lead assignment system"
app_email = "webdevelopersriaas@gmail.com"
app_license = "mit"

# Runtime integrations expect crm and sriaas_role_permissions to be installed.
# Keep this empty because Frappe treats required_apps as install sources and tries
# to fetch local custom apps from the remote app registry.
required_apps = []

after_install = "new_assignement_system.install.after_install"
after_migrate = "new_assignement_system.install.after_migrate"

doctype_js = {
	"CRM Lead": "public/js/crm_lead_form.js",
	"New Assignement System Rule": "public/js/rule_form.js",
}

doctype_list_js = {
	"CRM Lead": "public/js/crm_lead_list.js",
}

doc_events = {
	"CRM Lead": {
		"before_validate": ["new_assignement_system.events.crm_lead.before_validate"],
		"after_insert": ["new_assignement_system.events.crm_lead.after_insert"],
		"on_update": ["new_assignement_system.events.crm_lead.on_update"],
	},
	"ToDo": {
		"on_trash": ["new_assignement_system.events.todo.on_trash"],
	},
}

scheduler_events = {
	"cron": {
		"* * * * *": [
			"new_assignement_system.jobs.process_due_short_queue",
		],
		"*/5 * * * *": [
			"new_assignement_system.jobs.retry_failed_queue",
			"new_assignement_system.jobs.enqueue_stale_reassignment_candidates",
		],
		"0 * * * *": [
			"new_assignement_system.jobs.repair_agent_state_sample",
		],
		"5 0 * * *": [
			"new_assignement_system.jobs.reset_daily_agent_counts",
		],
		"30 2 * * *": [
			"new_assignement_system.jobs.rebuild_agent_states",
			"new_assignement_system.jobs.repair_assignment_helpers",
		],
	}
}

fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "New Assignement System"]]},
	{"dt": "Property Setter", "filters": [["module", "=", "New Assignement System"]]},
]
