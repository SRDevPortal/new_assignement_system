from __future__ import annotations

import frappe


def after_install() -> None:
	after_migrate()


def after_migrate() -> None:
	from new_assignement_system.patches.v1_0.ensure_indexes import execute

	execute()

	if frappe.db.exists("DocType", "New Assignement System Settings"):
		settings = frappe.get_single("New Assignement System Settings")
		if not settings.enabled:
			settings.enabled = 1
		settings.save(ignore_permissions=True)
