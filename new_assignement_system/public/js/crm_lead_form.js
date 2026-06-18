frappe.ui.form.on("CRM Lead", {
	refresh(frm) {
		frappe.call({
			method: "new_assignement_system.api.context.get_new_assignement_system_context",
			callback(r) {
				const context = r.message || {};
				if (context.enabled && context.disable_manual_assign_to) {
					frm.page.disable_assign_to = true;
				}
			},
		});
	},
});

