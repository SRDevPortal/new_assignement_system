"""Opt-in real transaction tests against isolated local tables."""
import os
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch
import frappe
from new_assignement_system.maintenance import reconciliation as mod


@unittest.skipUnless(os.environ.get("LOCAL_PHONE_TEST_SITE"),"explicit local test site required")
class ReconciliationMariaDBTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        site=os.environ["LOCAL_PHONE_TEST_SITE"]
        if not site.endswith((".local",".localhost")):raise ValueError("Local site required")
        frappe.init(site=site);frappe.connect();frappe.set_user("Administrator")
    @classmethod
    def tearDownClass(cls):frappe.destroy()
    def setUp(self):
        self.prefix="_nas_test_"+uuid.uuid4().hex
        self.leads=self.prefix+"_leads";self.work=self.prefix+"_work"
        self.sql=frappe.db.sql
        self.sql(f"CREATE TABLE `{self.leads}` (name varchar(140) PRIMARY KEY,lead_owner varchar(140),sr_dedupe_result varchar(40),sr_dedupe_stage varchar(40),sr_is_duplicate int,sr_is_archived int,sr_assignment_stage varchar(40)) ENGINE=InnoDB")
        self.sql(f"CREATE TABLE `{self.work}` (name varchar(140) PRIMARY KEY,lead varchar(140),revision int,due_at datetime(6),creation datetime(6),modified datetime(6),owner varchar(140),modified_by varchar(140), INDEX due_idx(due_at)) ENGINE=InnoDB")
        self.sql(f"INSERT INTO `{self.leads}` VALUES ('A','agent','Duplicate','Completed',1,0,'Assigned'),('B','agent','Primary','Completed',0,0,'Ready')")
        frappe.db.commit();self.other=frappe.db.get_connection()
        def sql(q,*args,**kwargs):
            return self.sql(q.replace("`tabCRM Lead`",f"`{self.leads}`").replace("`tabAssignment Reconciliation`",f"`{self.work}`"),*args,**kwargs)
        def set_stage(name,stage,**kwargs):self.sql(f"UPDATE `{self.leads}` SET sr_assignment_stage=%s WHERE name=%s",(stage,name))
        self.patches=[patch.object(frappe.db,"sql",side_effect=sql),patch.object(frappe.db,"get_global",return_value=1),
          patch.object(mod,"capture_enabled",return_value=True),patch.object(mod,"now_datetime",return_value=datetime(2026,11,18,12)),
          patch("new_assignement_system.engine.lead_state.set_assignment_state",side_effect=set_stage)]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.other.rollback();self.other.close();frappe.db.rollback()
        self.sql(f"DROP TABLE `{self.work}`");self.sql(f"DROP TABLE `{self.leads}`");frappe.db.commit()
    def test_signal_rolls_back_with_source_transaction(self):
        mod.mark_leads(["A"]);frappe.db.rollback()
        self.assertEqual(self.sql(f"SELECT COUNT(*) FROM `{self.work}`")[0][0],0)
    def test_coalesced_signals_process_and_preserve_ownership(self):
        mod.mark_leads(["A","B"]);mod.mark_leads(["A"]);frappe.db.commit()
        self.assertEqual(self.sql(f"SELECT revision FROM `{self.work}` WHERE name='A'")[0][0],2)
        self.assertEqual(mod.process_due(),2)
        self.assertEqual(self.sql(f"SELECT lead_owner,sr_assignment_stage FROM `{self.leads}` ORDER BY name"),(("agent","Review Required"),("agent","Assigned")))
        self.assertEqual(mod.process_due(),0)
    def test_locked_lead_retains_pending_work(self):
        mod.mark_leads(["A"]);frappe.db.commit()
        with self.other.cursor() as c:c.execute(f"SELECT name FROM `{self.leads}` WHERE name='A' FOR UPDATE")
        self.assertEqual(mod.process_due(),0)
        self.assertEqual(self.sql(f"SELECT COUNT(*) FROM `{self.work}`")[0][0],1)
        self.other.rollback();frappe.db.rollback()
        self.sql(f"UPDATE `{self.work}` SET due_at='2026-11-18 11:59:00'");frappe.db.commit()
        self.assertEqual(mod.process_due(),1)
    def test_deleted_lead_is_acknowledged(self):
        mod.mark_leads(["deleted"]);frappe.db.commit()
        self.assertEqual(mod.process_due(),1)
        self.assertEqual(self.sql(f"SELECT COUNT(*) FROM `{self.work}`")[0][0],0)
