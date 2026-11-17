from datetime import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from new_assignement_system import jobs
from new_assignement_system.engine import queue, service
from new_assignement_system.engine.contention import AssignmentBusy


class WorkerContentionTests(TestCase):
    def test_busy_lead_is_deferred_before_any_processing_update(self):
        for error in (frappe.QueryTimeoutError, frappe.QueryDeadlockError):
            events = []
            db = MagicMock()
            db.exists.return_value = True
            db.rollback.side_effect = lambda: events.append("rollback")
            row = frappe._dict(name="Q", lead="L", event_type="Insert", attempts=1)
            with patch.object(frappe, "db", db), \
                 patch.object(jobs, "try_lock", return_value=row), \
                 patch.object(jobs, "get_lead_context", side_effect=error()) as lock, \
                 patch.object(jobs, "set_assignment_state") as state, \
                 patch.object(jobs, "auto_assign_lead") as assign, \
                 patch.object(jobs, "mark_retry", side_effect=lambda *a, **k: events.append("retry")) as retry:
                jobs.process_assignment_queue_item("Q")
            lock.assert_called_once_with("L", for_update=True)
            state.assert_not_called()
            assign.assert_not_called()
            self.assertEqual(events, ["rollback", "retry"])
            self.assertTrue(retry.call_args.kwargs["busy"])

    def test_retry_record_contention_leaves_competing_claim_untouched(self):
        db = MagicMock()
        row = frappe._dict(name="Q", lead="L", event_type="Insert", attempts=1)
        with patch.object(frappe, "db", db), \
             patch.object(jobs, "try_lock", return_value=row), \
             patch.object(jobs, "get_lead_context", side_effect=frappe.QueryTimeoutError()), \
             patch.object(jobs, "mark_retry", side_effect=frappe.QueryTimeoutError()):
            self.assertIsNone(jobs.process_assignment_queue_item("Q"))
        self.assertEqual(db.rollback.call_count, 2)
        db.commit.assert_not_called()
        db.set_value.assert_not_called()

    def test_maintenance_routes_to_provisioned_pool_and_falls_back_safely(self):
        for known, expected in (({'short':300},'short'),({'short':300,'assignment':300},'assignment')):
            with patch.object(jobs,'get_settings',return_value=frappe._dict(enabled=1,default_queue='short',scheduler_queue='assignment')), \
                 patch('frappe.utils.background_jobs.get_queues_timeout',return_value=known), \
                 patch.object(frappe,'enqueue') as enqueue:
                jobs.enqueue_scheduler_maintenance()
            self.assertEqual(enqueue.call_count,3)
            self.assertTrue(all(call.kwargs['queue']==expected and call.kwargs['deduplicate'] for call in enqueue.call_args_list))

    def test_both_advisory_locks_fail_without_waiting(self):
        db = MagicMock()
        db.sql.return_value = [(0,)]
        for lock in (service._round_robin_lock, service._fresh_capacity_lock):
            with self.subTest(lock=lock.__name__), patch.object(frappe, 'db', db):
                with self.assertRaises(AssignmentBusy):
                    with lock('test'):
                        self.fail('contended lock entered')
                self.assertEqual(db.sql.call_args.args[1][1], 0)

    def test_advisory_lock_released_after_failure(self):
        db = MagicMock()
        db.sql.return_value = [(1,)]
        with patch.object(frappe, 'db', db):
            with self.assertRaises(ValueError):
                with service._round_robin_lock('rule'):
                    raise ValueError('failure')
        self.assertIn('release_lock', db.sql.call_args.args[0])

    def test_dispatch_is_deduplicated_and_after_commit(self):
        with patch.object(queue, 'get_settings', return_value=frappe._dict(default_queue='assignment')), \
             patch.object(frappe, 'enqueue') as enqueue:
            queue.enqueue_queue_item('Q')
            queue.enqueue_queue_item('Q')
        first, second = [c.kwargs for c in enqueue.call_args_list]
        self.assertEqual(first['job_id'], second['job_id'])
        self.assertTrue(first['enqueue_after_commit'])
        self.assertTrue(first['deduplicate'])
        self.assertEqual(first['queue'], 'assignment')

    def test_capacity_backoff_is_bounded_and_increases(self):
        values = [queue.capacity_delay('Q', n) for n in (1, 2, 3, 4, 5, 1000000)]
        self.assertEqual(values, sorted(values))
        self.assertGreaterEqual(values[0], 60)
        self.assertLessEqual(values[-1], 930)
        self.assertEqual(values[-1], values[-2])

    def test_job_rolls_back_before_recording_contention(self):
        events = []
        db = MagicMock()
        db.exists.return_value = True
        db.rollback.side_effect = lambda: events.append('rollback')
        row = frappe._dict(name='Q', lead='L', event_type='Insert', attempts=1, locked_by='token')
        with patch.object(frappe, 'db', db), \
             patch.object(jobs, 'try_lock', return_value=row), \
             patch.object(jobs, 'set_assignment_state'), \
             patch.object(jobs, 'auto_assign_lead', side_effect=AssignmentBusy('busy')), \
             patch.object(jobs, 'mark_retry', side_effect=lambda *a, **k: events.append('retry')) as retry:
            jobs.process_assignment_queue_item('Q')
        self.assertEqual(events, ['rollback', 'retry'])
        self.assertTrue(retry.call_args.kwargs['busy'])

    def test_capacity_hold_does_not_consume_technical_attempt(self):
        db = MagicMock()
        db.exists.return_value = True
        row = frappe._dict(name='Q', lead='L', event_type='Insert', attempts=3, capacity_waits=4)
        with patch.object(frappe, 'db', db), \
             patch.object(jobs, 'try_lock', return_value=row), \
             patch.object(jobs, 'get_settings', return_value=frappe._dict(enable_fresh_slot_auto_refill=1)), \
             patch.object(jobs, 'now_datetime', return_value=datetime(2026, 11, 16, 12)), \
             patch.object(jobs, 'sanitize_for_storage', side_effect=lambda value: value), \
             patch.object(jobs, 'set_assignment_state') as state, \
             patch.object(jobs, 'auto_assign_lead', return_value={'status':'skipped','reason':'No active agent below fresh lead limit'}):
            jobs.process_assignment_queue_item('Q')
        values = db.set_value.call_args.args[2]
        self.assertEqual(values['attempts'], 2)
        self.assertEqual(values['capacity_waits'], 5)
        self.assertEqual(values['status'], 'Retry')
        self.assertEqual(state.call_args.args[1], 'Capacity Hold')
        self.assertGreaterEqual(state.call_args.kwargs['retry_seconds'], 900)

    def test_future_queue_item_is_not_claimed(self):
        db = MagicMock()
        db.sql.return_value = [frappe._dict(status='Retry', next_retry_at=datetime(2030, 1, 1))]
        with patch.object(frappe, 'db', db), patch.object(queue, 'now_datetime', return_value=datetime(2026, 1, 1)):
            self.assertIsNone(queue.try_lock('Q'))
        db.set_value.assert_not_called()

    def test_newer_claim_is_not_overwritten_by_old_failure(self):
        db = MagicMock()
        db.sql.return_value = [frappe._dict(status='Processing', locked_by='new', attempts=1)]
        with patch.object(frappe, 'db', db):
            queue.mark_retry('Q', 'failed', 1, claim=frappe._dict(locked_by='old', lead='L'))
        db.set_value.assert_not_called()

    def test_committed_assignment_is_not_retried(self):
        db = MagicMock()
        db.sql.return_value = [frappe._dict(status='Processing', locked_by='old', attempts=1)]
        db.get_value.return_value = 'Assigned'
        with patch.object(frappe, 'db', db):
            queue.mark_retry('Q', 'failed', 1, claim=frappe._dict(locked_by='old', lead='L'))
        self.assertEqual(db.set_value.call_args.args[2]['status'], 'Assigned')

    def test_nowait_contention_releases_transaction(self):
        db = MagicMock()
        with patch.object(frappe, 'db', db), patch.object(jobs, 'try_lock', side_effect=frappe.QueryTimeoutError('busy')):
            jobs.process_assignment_queue_item('Q')
        db.rollback.assert_called_once()

    def test_old_site_schema_does_not_select_missing_counter(self):
        db=MagicMock(); db.has_column.return_value=False; db.sql.return_value=[]
        with patch.object(frappe,'db',db):
            self.assertIsNone(queue.try_lock('Q'))
        self.assertIn('0 as capacity_waits',db.sql.call_args.args[0])

    def test_watchdog_does_not_recover_live_rq_job(self):
        db=MagicMock()
        with patch.object(frappe,'db',db),patch.object(frappe,'get_all',return_value=['Q']), \
             patch.object(queue,'now_datetime',return_value=datetime(2026,11,16,12)), \
             patch('frappe.utils.background_jobs.is_job_enqueued',return_value=True):
            queue.recover_abandoned_claims()
        db.sql.assert_not_called()

    def test_watchdog_revalidates_age_under_lock(self):
        db=MagicMock();db.sql.return_value=[]
        with patch.object(frappe,'db',db),patch.object(frappe,'get_all',return_value=['Q']), \
             patch.object(queue,'now_datetime',return_value=datetime(2026,11,16,12)), \
             patch('frappe.utils.background_jobs.is_job_enqueued',return_value=False), \
             patch.object(queue,'mark_retry') as retry:
            queue.recover_abandoned_claims()
        self.assertIn("status='Processing' and locked_at <",db.sql.call_args.args[0])
        retry.assert_not_called()

    def test_bulk_retries_only_failed_lead_after_rollback(self):
        events = []
        db = MagicMock()
        db.commit.side_effect = lambda: events.append("commit")
        db.rollback.side_effect = lambda: events.append("rollback")
        def assign(lead, *args, **kwargs):
            events.append(lead)
            if events.count("B") == 1 and lead == "B":
                raise frappe.QueryTimeoutError()
            return {"status": "assigned" if lead == "A" else "skipped"}
        with patch.object(frappe, "db", db), patch.object(service, "assign_lead", side_effect=assign), \
             patch.object(jobs.time, "sleep"):
            result = jobs.bulk_assign(["A", "B"], "agent")
        self.assertEqual(events, ["A", "commit", "B", "rollback", "B", "commit"])
        self.assertEqual(result, {"status": "ok", "updated": 1, "skipped": 1})

    def test_bulk_contention_is_bounded_and_never_reported_as_success(self):
        db = MagicMock()
        with patch.object(frappe, "db", db), patch.object(service, "assign_lead", side_effect=AssignmentBusy) as assign, \
             patch.object(jobs.time, "sleep"):
            with self.assertRaises(AssignmentBusy):
                jobs.bulk_assign(["A"], "agent")
        self.assertEqual(assign.call_count, 3)
        self.assertEqual(db.rollback.call_count, 3)
        db.commit.assert_not_called()
