(() => {
	const DT = "CRM Lead";
	const settings = frappe.listview_settings[DT] || {};
	const previousOnload = settings.onload;

	settings.onload = function (listview) {
		if (previousOnload) previousOnload.call(this, listview);

		frappe.call({
			method: "new_assignement_system.api.context.get_new_assignement_system_context",
			callback(r) {
				const context = r.message || {};
				if (!context.enabled || !context.can_manage_assignment) return;
				addAssignmentActions(listview, context);
			},
		});
	};

	frappe.listview_settings[DT] = settings;

	function selectedNames(listview) {
		return (listview.get_checked_items() || []).map((row) => row.name);
	}

	function addAssignmentActions(listview, context) {
		listview.page.add_actions_menu_item(__("Assign Lead"), () => {
			const leads = selectedNames(listview);
			if (!leads.length) {
				frappe.msgprint(__("Please select at least one CRM Lead"));
				return;
			}

			frappe.prompt(
				[
					{
						fieldname: "new_owner",
						label: __("Assign To"),
						fieldtype: "Link",
						options: "User",
						reqd: 1,
						get_query() {
							const users = context.managed_team_users || [];
							return users.length ? { filters: { name: ["in", users], enabled: 1 } } : { filters: { enabled: 1 } };
						},
					},
				],
				(values) => {
					frappe.call({
						method: "new_assignement_system.api.manual.assign_crm_leads",
						args: { leads, new_owner: values.new_owner },
						freeze: true,
						callback(r) {
							const status = (r.message || {}).status;
							frappe.show_alert({
								message: status === "queued" ? __("Lead assignment queued") : __("Lead assigned"),
								indicator: "green",
							});
							listview.refresh();
						},
					});
				},
				__("Assign Lead"),
				__("Assign"),
			);
		});

		listview.page.add_actions_menu_item(__("Clear Lead Assignment"), () => {
			const leads = selectedNames(listview);
			if (!leads.length) {
				frappe.msgprint(__("Please select at least one CRM Lead"));
				return;
			}

			frappe.confirm(__("Clear assignment for selected CRM Leads?"), () => {
				frappe.call({
					method: "new_assignement_system.api.manual.clear_crm_leads",
					args: { leads },
					freeze: true,
					callback(r) {
						const status = (r.message || {}).status;
						frappe.show_alert({
							message: status === "queued" ? __("Lead assignment clear queued") : __("Lead assignment cleared"),
							indicator: "green",
						});
						listview.refresh();
					},
				});
			});
		});
	}
})();

