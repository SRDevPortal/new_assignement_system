"""Real SQL/locking tests on a disposable, socket-only MariaDB instance.

Never connects to a configured site database. Requires mariadb-install-db and
mariadbd on PATH; the daemon runs as the invoking non-root user.
"""
import os
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch

import frappe
import pymysql
from new_assignement_system.engine import eligibility, queue, strategies


class Database:
    def __init__(self, connection):
        self.connection = connection

    def sql(self, query, values=None, as_dict=False):
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, values)
                rows = cursor.fetchall()
                if as_dict:
                    columns = [c[0] for c in cursor.description]
                    return [frappe._dict(zip(columns, row)) for row in rows]
                return rows
        except pymysql.err.OperationalError as error:
            if error.args[0] == 1205:
                raise frappe.QueryTimeoutError(str(error)) from error
            raise

    def set_value(self, doctype, name, values, **kwargs):
        columns = ', '.join('`'+key+'`=%s' for key in values)
        self.sql('UPDATE `tab'+doctype+'` SET '+columns+' WHERE name=%s', [*values.values(), name])

    def exists(self, *args):
        return True

    def has_column(self, *args):
        return True


@skipUnless(shutil.which('mariadbd') and shutil.which('mariadb-install-db'), 'requires disposable MariaDB tooling')
class MariaDBContentionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix='nas-contention-')
        cls.root = Path(cls.folder.name)
        cls.output = (cls.root/'bootstrap.log').open('w')
        subprocess.run(['mariadb-install-db', '--no-defaults', '--datadir='+str(cls.root/'data'),
                        '--auth-root-authentication-method=normal', '--skip-test-db'],
                       check=True, stdout=cls.output, stderr=subprocess.STDOUT, timeout=45)
        cls.socket = str(cls.root/'db.sock')
        cls.server = subprocess.Popen(['mariadbd', '--no-defaults', '--datadir='+str(cls.root/'data'),
            '--socket='+cls.socket, '--pid-file='+str(cls.root/'db.pid'), '--skip-networking',
            '--skip-log-bin', '--innodb-buffer-pool-size=64M', '--max-connections=15',
            '--log-error='+str(cls.root/'server.log')], stdout=cls.output, stderr=subprocess.STDOUT)
        for _ in range(200):
            try:
                cls.admin = pymysql.connect(unix_socket=cls.socket, user='root', autocommit=True)
                break
            except pymysql.err.OperationalError:
                if cls.server.poll() is not None:
                    raise RuntimeError((cls.root/'server.log').read_text())
                time.sleep(.1)
        else:
            cls.server.terminate()
            raise RuntimeError('Disposable MariaDB did not start')
        with cls.admin.cursor() as cursor:
            cursor.execute('CREATE DATABASE worker_test')
        cls.a = cls.connect()
        cls.b = cls.connect()
        cls.db = Database(cls.a)
        cls.db.sql('''CREATE TABLE `tabNew Assignement System Queue` (
            name varchar(140) PRIMARY KEY, lead varchar(140), event_type varchar(40),
            status varchar(40), attempts int DEFAULT 0, capacity_waits int DEFAULT 0,
            next_retry_at datetime(6), locked_by varchar(140), locked_at datetime(6)
        ) ENGINE=InnoDB''')
        cls.db.sql('''CREATE TABLE `tabNew Assignement System Log` (
            name int PRIMARY KEY AUTO_INCREMENT, rule varchar(140), new_owner varchar(140),
            action varchar(140), status varchar(140), creation datetime(6),
            INDEX idx_nas_rule_owner_status_action_created (rule,new_owner,status,action,creation)
        ) ENGINE=InnoDB ROW_FORMAT=DYNAMIC''')
        cls.db.sql('CREATE TABLE `tabCRM Lead` (\n            name varchar(140) PRIMARY KEY, lead_owner varchar(140), status varchar(40),\n            converted int DEFAULT 0,\n            INDEX idx_nas_owner_status_converted (lead_owner,status,converted)\n        ) ENGINE=InnoDB')
        cls.a.commit()

    @classmethod
    def connect(cls):
        return pymysql.connect(unix_socket=cls.socket, user='root', database='worker_test', autocommit=False)

    @classmethod
    def tearDownClass(cls):
        cls.a.close(); cls.b.close(); cls.admin.close()
        cls.server.terminate(); cls.server.wait(timeout=20)
        cls.output.close(); cls.folder.cleanup()

    def setUp(self):
        clock = patch.object(queue, 'now_datetime', return_value=datetime(2026,11,16,12))
        clock.start(); self.addCleanup(clock.stop)
        self.a.rollback(); self.b.rollback()
        self.db.sql('DELETE FROM `tabNew Assignement System Queue`')
        self.db.sql('DELETE FROM `tabNew Assignement System Log`')
        self.db.sql("DELETE FROM `tabCRM Lead`")
        self.db.sql("INSERT INTO `tabNew Assignement System Queue` (name,lead,event_type,status) VALUES ('Q','L','Insert','Pending')")
        self.a.commit()

    def test_second_worker_cannot_claim_locked_or_committed_processing_item(self):
        with patch.object(frappe, 'db', self.db):
            first = queue.try_lock('Q')
        self.assertEqual(first.attempts, 1)
        started = time.monotonic()
        with patch.object(frappe, 'db', Database(self.b)):
            with self.assertRaises(frappe.QueryTimeoutError):
                queue.try_lock('Q')
        self.assertLess(time.monotonic()-started, 2)
        self.b.rollback(); self.a.commit()
        with patch.object(frappe, 'db', Database(self.b)):
            self.assertIsNone(queue.try_lock('Q'))
        self.b.rollback()
        self.assertEqual(self.db.sql("SELECT attempts FROM `tabNew Assignement System Queue` WHERE name='Q'")[0][0], 1)

    def test_rolled_back_claim_is_recoverable(self):
        with patch.object(frappe, 'db', self.db):
            first = queue.try_lock('Q')
        self.a.rollback()
        with patch.object(frappe, 'db', Database(self.b)):
            second = queue.try_lock('Q')
        self.assertEqual(second.attempts, 1)
        self.assertNotEqual(first.locked_by, second.locked_by)
        self.b.commit()

    def test_latest_lookup_matches_original_aggregate(self):
        now = datetime(2026,11,16,12)
        fixtures = [
            ('R','A','Assigned','Success',now-timedelta(days=10)),
            ('R','A','Reassigned','Success',now-timedelta(days=2)),
            ('R','A','Assigned','Failed',now),
            ('R','A','Skipped','Success',now),
            ('OTHER','A','Assigned','Success',now),
            ('R','B','Assigned','Success',now-timedelta(days=1)),
        ]
        for row in fixtures:
            self.db.sql('INSERT INTO `tabNew Assignement System Log` (rule,new_owner,action,status,creation) VALUES (%s,%s,%s,%s,%s)',row)
        self.a.commit()
        expected = dict(self.db.sql("SELECT new_owner,MAX(creation) FROM `tabNew Assignement System Log` WHERE rule='R' AND status='Success' AND action IN ('Assigned','Reassigned') GROUP BY new_owner"))
        candidates = [frappe._dict(agent=name,current_open_leads=0) for name in ('A','B','C')]
        with patch.object(frappe, 'db', self.db):
            strategies._apply_rule_last_assigned(candidates,'R')
            selected = strategies._round_robin(candidates,'R')
        self.assertEqual({r.agent:r.rule_last_assigned_at for r in candidates}, {'A':expected['A'],'B':expected['B'],'C':None})
        self.assertEqual(selected.agent,'C')

    def test_covering_index_is_available_to_newest_lookup(self):
        for i in range(40):
            self.db.sql('INSERT INTO `tabNew Assignement System Log` (rule,new_owner,action,status,creation) VALUES (%s,%s,%s,%s,%s)',
                        ('R','A','Assigned','Success',datetime(2026,1,1)+timedelta(days=i)))
        plan = self.db.sql("EXPLAIN SELECT creation FROM `tabNew Assignement System Log` WHERE rule='R' AND new_owner='A' AND status='Success' AND action='Assigned' ORDER BY creation DESC LIMIT 1",as_dict=True)[0]
        self.assertEqual(plan.key,'idx_nas_rule_owner_status_action_created')
        self.assertIn('Using index',plan.Extra)

    def test_capacity_count_fails_fast_then_reads_latest_committed_capacity(self):
        self.db.sql("INSERT INTO `tabCRM Lead` VALUES ('L', 'agent', 'New', 0)")
        self.a.commit()
        # Establish a stale REPEATABLE READ snapshot before the competing commit.
        with self.b.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM `tabCRM Lead`")
        self.db.sql("INSERT INTO `tabCRM Lead` VALUES ('L2', 'agent', 'New', 0)")
        started = time.monotonic()
        with patch.object(frappe, "db", Database(self.b)):
            with self.assertRaises(frappe.QueryTimeoutError):
                eligibility.get_agent_fresh_lead_count("agent", "New", for_update=True)
        self.assertLess(time.monotonic() - started, 2)
        self.b.rollback()
        self.a.commit()
        with patch.object(frappe, "db", Database(self.b)):
            count = eligibility.get_agent_fresh_lead_count("agent", "New", for_update=True)
        self.assertEqual(count, 2)
        self.b.rollback()

    def test_capacity_uses_current_read_even_with_older_snapshot(self):
        self.db.sql("INSERT INTO `tabCRM Lead` VALUES ('L', 'agent', 'New', 0)")
        self.a.commit()
        with self.b.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM `tabCRM Lead`")
        self.db.sql("INSERT INTO `tabCRM Lead` VALUES ('L2', 'agent', 'New', 0)")
        self.a.commit()
        with patch.object(frappe, "db", Database(self.b)):
            count = eligibility.get_agent_fresh_lead_count("agent", "New", for_update=True)
        self.assertEqual(count, 2)
        self.b.rollback()
