"""Transactional reconciliation outbox. Historical initialization is Bench-only."""
import hashlib
from contextlib import contextmanager
import frappe
from frappe.utils import cint, now_datetime, add_to_date

TABLE = "tabAssignment Reconciliation"
FIELDS = ("lead_owner", "sr_dedupe_result", "sr_dedupe_stage", "sr_is_duplicate", "sr_is_archived", "sr_assignment_stage")
CURSOR = "nas_reconciliation_init_cursor"
DONE = "nas_reconciliation_initialized"


def capture_enabled():
    return bool(cint(frappe.conf.get("nas_reconciliation_capture")) or cint(frappe.conf.get("nas_incremental_reconciliation")))


def mark_leads(names):
    if not capture_enabled():
        return
    # Missing schema while capture is enabled is a deployment error, not lost work.
    for name in sorted(set(names)):
        frappe.db.sql(f"""INSERT INTO `{TABLE}`
            (name,lead,revision,due_at,creation,modified,owner,modified_by)
            VALUES (%s,%s,1,%s,%s,%s,'Administrator','Administrator')
            ON DUPLICATE KEY UPDATE revision=revision+1,
              due_at=LEAST(COALESCE(due_at,VALUES(due_at)),VALUES(due_at)), modified=VALUES(modified)""",
            (name,name,now_datetime(),now_datetime(),now_datetime()))


def on_lead_update(doc, method=None):
    if capture_enabled() and (doc.is_new() or any(doc.has_value_changed(f) for f in FIELDS)):
        mark_leads([doc.name])


def desired_stage(row):
    if not row.get("lead_owner"):
        return None
    if row.get("sr_dedupe_result") == "Duplicate" or cint(row.get("sr_is_duplicate")) or cint(row.get("sr_is_archived")):
        return "Review Required" if row.get("sr_assignment_stage") != "Review Required" else None
    if (row.get("sr_dedupe_stage") == "Completed" and row.get("sr_dedupe_result") == "Primary"
            and row.get("sr_assignment_stage") in ("Waiting for Dedupe", "Ready", "Queued", "Failed")):
        return "Assigned"
    return None


def process_due(limit=100):
    if not cint(frappe.db.get_global(DONE)):
        raise RuntimeError("Initialize reconciliation through Bench before activation")
    names = frappe.db.sql(f"SELECT name FROM `{TABLE}` WHERE due_at<=%s ORDER BY due_at,name LIMIT %s",
                          (now_datetime(),max(1,min(cint(limit) or 100,500))),pluck=True)
    old = frappe.db.sql("SELECT @@SESSION.innodb_lock_wait_timeout")[0][0]
    processed = 0
    try:
        frappe.db.sql("SET SESSION innodb_lock_wait_timeout=3")
        for name in names:
            try:
                # Match writer lock order: lead first, then outbox. No external calls.
                rows = frappe.db.sql("SELECT " + ",".join("`"+f+"`" for f in FIELDS) +
                    " FROM `tabCRM Lead` WHERE name=%s FOR UPDATE NOWAIT", (name,),as_dict=True)
                work = frappe.db.sql(f"SELECT revision,due_at FROM `{TABLE}` WHERE name=%s FOR UPDATE NOWAIT",
                                     (name,),as_dict=True)
                if not work or work[0].due_at > now_datetime():
                    frappe.db.rollback()
                    continue
                if rows:
                    stage = desired_stage(rows[0])
                    if stage:
                        from new_assignement_system.engine.lead_state import set_assignment_state
                        reason = ("Assigned lead was later classified as a duplicate; ownership was preserved"
                                  if stage == "Review Required" else "Existing owner retained after dedupe")
                        set_assignment_state(name,stage,reason=reason)
                frappe.db.sql(f"DELETE FROM `{TABLE}` WHERE name=%s AND revision=%s",(name,work[0].revision))
                frappe.db.commit()
                processed += 1
            except (frappe.QueryTimeoutError, frappe.QueryDeadlockError):
                frappe.db.rollback()
                # Pending row remains durable. Delay only an already-due item; no deletion.
                try:
                    frappe.db.sql(f"UPDATE `{TABLE}` SET due_at=%s WHERE name=%s AND due_at<=%s",
                                  (add_to_date(now_datetime(),seconds=30),name,now_datetime()))
                    frappe.db.commit()
                except (frappe.QueryTimeoutError, frappe.QueryDeadlockError):
                    frappe.db.rollback()
            except Exception:
                frappe.db.rollback()
                raise
    finally:
        frappe.db.sql("SET SESSION innodb_lock_wait_timeout=%s",(old,))
    return processed


@contextmanager
def _init_lock():
    key="nas-init:"+hashlib.sha256(str(frappe.local.site).encode()).hexdigest()[:48]
    if frappe.db.sql("SELECT GET_LOCK(%s,0)",(key,))[0][0] != 1:
        raise RuntimeError("Initialization is already running")
    try: yield
    finally: frappe.db.sql("SELECT RELEASE_LOCK(%s)",(key,))


def initialize(batch_size=200, dry_run=True):
    """One resumable page. Enable capture BEFORE starting, then activate only when done."""
    frappe.only_for("System Manager")
    if not isinstance(dry_run,bool): raise ValueError("dry_run must be a JSON boolean")
    if not capture_enabled(): raise RuntimeError("Enable nas_reconciliation_capture before initialization")
    with _init_lock():
        if cint(frappe.db.get_global(DONE)):
            return dict(done=True,status="already_initialized")
        cursor=frappe.db.get_global(CURSOR) or ""
        names=frappe.get_all("CRM Lead",filters={"name":[">",cursor]} if cursor else None,
                             pluck="name",order_by="name asc",limit_page_length=max(1,min(cint(batch_size) or 200,500)))
        done=len(names)<max(1,min(cint(batch_size) or 200,500))
        if not dry_run:
            old_timeout = frappe.db.sql("SELECT @@SESSION.innodb_lock_wait_timeout")[0][0]
            try:
                frappe.db.sql("SET SESSION innodb_lock_wait_timeout=3")
                mark_leads(names)
                if names: frappe.db.set_global(CURSOR,names[-1])
                if done: frappe.db.set_global(DONE,1)
                frappe.db.commit()
            except Exception:
                frappe.db.rollback()
                raise
            finally:
                frappe.db.sql("SET SESSION innodb_lock_wait_timeout=%s", (old_timeout,))
        return dict(done=done,dry_run=dry_run,processed=len(names),last_name=names[-1] if names else cursor)


def status():
    frappe.only_for("System Manager")
    return dict(capture_enabled=capture_enabled(), initialized=bool(cint(frappe.db.get_global(DONE))),
                last_name=frappe.db.get_global(CURSOR) or "",
                active=bool(cint(frappe.conf.get("nas_incremental_reconciliation"))))
