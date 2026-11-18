"""Read-only Bench assessment. No deletion, scheduling or retention defaults."""
from datetime import timedelta
import frappe
from frappe.utils import get_datetime, now_datetime

DOCTYPE = "New Assignement System Log"
OPERATIONAL_ACTIONS = frozenset(("Assigned", "Reassigned", "Unassigned"))


def assess(keep_days, after_name="", batch_size=200, as_of=None):
    """Inspect one primary-key page. Carry as_of and next_after_name across pages.

    Counts overlap: a successful assignment may also reference a queue. Review
    candidates are NOT deletion approval; external reports/integrations can depend
    on them. This traversal is not a transactionally consistent global snapshot.
    """
    frappe.only_for("System Manager")
    if type(keep_days) is not int or keep_days < 1:
        raise ValueError("keep_days must be an explicit positive JSON integer")
    if type(batch_size) is not int or not 1 <= batch_size <= 500:
        raise ValueError("batch_size must be an integer between 1 and 500")
    if not isinstance(after_name, str):
        raise ValueError("after_name must be a string")
    anchor = get_datetime(as_of) if as_of else now_datetime()
    cutoff = anchor - timedelta(days=keep_days)
    rows = frappe.get_all(DOCTYPE,
        filters={"name": [">", after_name]} if after_name else None,
        fields=["name", "creation", "status", "action", "queue"],
        order_by="name asc", limit_page_length=batch_size)
    counts = dict(scanned=len(rows), old=0, recent=0, unknown_creation=0,
                  protected_success=0, protected_queue=0, review_candidates=0)
    for row in rows:
        if not row.get("creation"):
            counts["unknown_creation"] += 1
            continue
        if get_datetime(row.creation) >= cutoff:
            counts["recent"] += 1
            continue
        counts["old"] += 1
        success = row.get("status") == "Success" and row.get("action") in OPERATIONAL_ACTIONS
        queued = bool(row.get("queue"))
        counts["protected_success"] += int(success)
        counts["protected_queue"] += int(queued)
        counts["review_candidates"] += int(not success and not queued)
    return dict(read_only=True, deletion_enabled=False, keep_days=keep_days,
                as_of=str(anchor), cutoff=str(cutoff), counts=counts,
                next_after_name=rows[-1].name if rows else after_name,
                done=len(rows) < batch_size)
