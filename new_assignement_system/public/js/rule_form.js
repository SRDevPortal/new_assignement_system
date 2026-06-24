frappe.ui.form.on("New Assignement System Rule", {
	setup(frm) {
		set_assign_user_query(frm);
	},

	refresh(frm) {
		load_team_members(frm);
		set_assign_user_query(frm);
	},

	team(frm) {
		load_team_members(frm);
		set_assign_user_query(frm);
	},
});

function load_team_members(frm) {
	if (!frm.doc.team) {
		frm._nas_team_members = [];
		return;
	}

	frappe.call({
		method: "new_assignement_system.api.rules.get_team_members",
		args: {
			team: frm.doc.team,
		},
		callback(r) {
			frm._nas_team_members = r.message || [];
			refresh_assign_user_query(frm);
		},
	});
}

function set_assign_user_query(frm) {
	const grid = frm.fields_dict.assign_to_users && frm.fields_dict.assign_to_users.grid;
	if (!grid) return;

	grid.get_field("user").get_query = () => {
		if (!frm.doc.team) {
			return {
				filters: {
					enabled: 1,
				},
			};
		}

		const members = frm._nas_team_members || [];
		return {
			filters: {
				name: ["in", members.length ? members : [""]],
				enabled: 1,
			},
		};
	};
}

function refresh_assign_user_query(frm) {
	const grid = frm.fields_dict.assign_to_users && frm.fields_dict.assign_to_users.grid;
	if (grid) {
		grid.refresh();
	}
}
