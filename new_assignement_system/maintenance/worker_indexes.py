"""Explicit, offline-operated index installation; never called by migrate/hooks.

Run in a dedicated bench execute process after resource/backup checks. Default
is a read-only plan. No arbitrary SQL/table/index identifiers are accepted.
"""
import frappe

TARGETS = {
    'assignment': ('tabNew Assignement System Log', 'idx_nas_rule_owner_status_action_created',
                   ('rule','new_owner','status','action','creation')),
    'chat_report': ('tabChat Message', 'idx_chat_sender_creation_delivery',
                    ('sender_type','creation','direction','delivery_status')),
}


def install(target='assignment', apply=False):
    if target not in TARGETS:
        raise ValueError('target must be assignment or chat_report')
    if not isinstance(apply, bool):
        raise ValueError('apply must be a JSON boolean')
    table, name, columns = TARGETS[target]
    rows = frappe.db.sql('''SELECT INDEX_NAME, COLUMN_NAME, SUB_PART FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s ORDER BY INDEX_NAME,SEQ_IN_INDEX''',
        (table,), as_dict=True)
    definitions = {}
    for row in rows:
        definitions.setdefault(row.INDEX_NAME, []).append((row.COLUMN_NAME, row.SUB_PART))
    expected = [(column, None) for column in columns]
    if name in definitions and definitions[name] != expected:
        raise ValueError('Existing index name has a different definition; DBA review required')
    if expected in definitions.values():
        return {'target':target,'status':'already_present'}
    if not rows:
        raise ValueError('Required table is absent; install the owning app first')
    query = 'ALTER TABLE `'+table+'` ADD INDEX `'+name+'` ('+', '.join('`'+c+'`' for c in columns)+'), ALGORITHM=INPLACE, LOCK=NONE'
    if not apply:
        return {'target':target,'status':'planned','sql':query}
    old = frappe.db.sql('SELECT @@SESSION.lock_wait_timeout')[0][0]
    try:
        # Avoid queueing behind a long metadata lock. This is distinct from
        # innodb_lock_wait_timeout and does not bound index-building runtime.
        frappe.db.sql('SET SESSION lock_wait_timeout=10')
        frappe.db.sql(query)
    finally:
        frappe.db.sql('SET SESSION lock_wait_timeout=%s',(old,))
    return {'target':target,'status':'created'}
