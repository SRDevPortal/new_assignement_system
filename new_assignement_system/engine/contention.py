"""Expected assignment serialization contention, handled at transaction boundaries."""
import frappe


class AssignmentBusy(frappe.ValidationError):
	"""No work was assigned; release the transaction and defer the attempt."""
