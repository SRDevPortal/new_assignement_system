from __future__ import annotations

import frappe
from frappe.utils import now_datetime, nowdate

from new_assignement_system.settings import get_settings


def sync_assignment_helpers(
	lead: str,
	owner: str | None,
	*,
	description: str | None = None,
	sync_todo: bool | None = None,
	sync_docshare: bool | None = None,
) -> None:
	settings = get_settings()
	if sync_todo is None:
		sync_todo = bool(settings.sync_todo)
	if sync_docshare is None:
		sync_docshare = bool(settings.sync_docshare)

	todo_created = False
	if sync_todo:
		todo_created = _sync_todo(lead, owner, description=description)
	if sync_docshare:
		_sync_docshare(lead, owner)
	if owner and todo_created:
		_sync_crm_notification(lead, owner)


def clear_assignment_helpers(lead: str) -> None:
	_sync_todo(lead, None)
	_sync_docshare(lead, None)


def sync_crm_notification(lead: str, owner: str) -> None:
	_sync_crm_notification(lead, owner)


def _sync_todo(lead: str, owner: str | None, *, description: str | None = None) -> bool:
	frappe.db.sql(
		"""
		update `tabToDo`
		set status = 'Closed',
			modified = %s,
			modified_by = %s
		where reference_type = 'CRM Lead'
		  and reference_name = %s
		  and status = 'Open'
		  and (%s is null or allocated_to != %s)
		""",
		(now_datetime(), frappe.session.user, lead, owner, owner),
	)
	if not owner:
		return False

	if frappe.db.exists(
		"ToDo",
		{
			"reference_type": "CRM Lead",
			"reference_name": lead,
			"allocated_to": owner,
			"status": "Open",
		},
	):
		return False

	todo = frappe.new_doc("ToDo")
	todo.name = frappe.generate_hash(length=10)
	todo.update(
		{
			"allocated_to": owner,
			"reference_type": "CRM Lead",
			"reference_name": lead,
			"description": description or f"Assignment for CRM Lead {lead}",
			"priority": "Medium",
			"status": "Open",
			"date": nowdate(),
			"assigned_by": frappe.session.user,
			"owner": frappe.session.user,
			"creation": now_datetime(),
			"modified": now_datetime(),
			"modified_by": frappe.session.user,
		}
	)
	todo.db_insert()
	return True


def _sync_docshare(lead: str, owner: str | None) -> None:
	frappe.db.delete("DocShare", {"share_doctype": "CRM Lead", "share_name": lead})
	if not owner:
		return

	share = frappe.new_doc("DocShare")
	share.name = frappe.generate_hash(length=10)
	share.update(
		{
			"user": owner,
			"share_doctype": "CRM Lead",
			"share_name": lead,
			"read": 1,
			"write": 1,
			"share": 0,
			"submit": 0,
			"everyone": 0,
			"notify_by_email": 0,
			"owner": frappe.session.user,
			"creation": now_datetime(),
			"modified": now_datetime(),
			"modified_by": frappe.session.user,
		}
	)
	share.db_insert()


def _sync_crm_notification(lead: str, owner: str) -> None:
	if not frappe.db.exists("DocType", "CRM Notification"):
		return
	if owner == frappe.session.user:
		return

	lead_doc = frappe.db.get_value(
		"CRM Lead",
		lead,
		["lead_name", "first_name", "name"],
		as_dict=True,
	)
	if not lead_doc:
		return

	from_user_full_name = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
	lead_label = lead_doc.lead_name or lead_doc.first_name or lead_doc.name
	message = f"{from_user_full_name} assigned a CRM Lead {lead} to you"
	notification_text = f"""
            <div class="mb-2 leading-5 text-ink-gray-5">
                <span class="font-medium text-ink-gray-9">{frappe.utils.escape_html(from_user_full_name)}</span>
                <span>assigned a lead <span class="font-medium text-ink-gray-9">{frappe.utils.escape_html(lead_label)}</span> to you</span>
            </div>
        """
	values = {
		"from_user": frappe.session.user,
		"to_user": owner,
		"type": "Assignment",
		"message": message,
		"notification_text": notification_text,
		"notification_type_doctype": "CRM Lead",
		"notification_type_doc": lead,
		"reference_doctype": "CRM Lead",
		"reference_name": lead,
	}
	if frappe.db.exists("CRM Notification", values):
		return

	doc = frappe.get_doc({"doctype": "CRM Notification", **values})
	doc.insert(ignore_permissions=True)
