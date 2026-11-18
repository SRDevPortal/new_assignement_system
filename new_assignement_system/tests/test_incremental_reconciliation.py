import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
import frappe
from new_assignement_system.maintenance import reconciliation as mod


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        p=patch.object(mod,"now_datetime",return_value=datetime(2026,11,18,12))
        p.start();self.addCleanup(p.stop)

    def test_state_equivalence(self):
        base=dict(lead_owner="agent",sr_assignment_stage="Assigned")
        for field,value in [("sr_dedupe_result","Duplicate"),("sr_is_duplicate",1),("sr_is_archived",1)]:
            self.assertEqual(mod.desired_stage({**base,field:value}),"Review Required")
        self.assertIsNone(mod.desired_stage({**base,"sr_is_duplicate":1,"sr_assignment_stage":"Review Required"}))
        self.assertIsNone(mod.desired_stage({**base,"lead_owner":"","sr_is_duplicate":1}))
        self.assertEqual(mod.desired_stage({**base,"sr_assignment_stage":"Ready","sr_dedupe_stage":"Completed","sr_dedupe_result":"Primary"}),"Assigned")
        self.assertIsNone(mod.desired_stage({**base,"sr_assignment_stage":"Review Required","sr_dedupe_stage":"Completed","sr_dedupe_result":"Primary"}))

    @patch.object(mod,"frappe")
    def test_signals_are_transactional_and_coalesced(self,f):
        f.conf={"nas_reconciliation_capture":1}
        mod.mark_leads(["B","A","A"])
        self.assertEqual(f.db.sql.call_count,2)
        self.assertIn("revision=revision+1",f.db.sql.call_args_list[0].args[0])
        self.assertEqual(f.db.sql.call_args_list[0].args[1][0],"A")
        f.db.commit.assert_not_called()

    @patch.object(mod,"frappe")
    def test_disabled_capture_has_no_writes(self,f):
        f.conf={}
        mod.mark_leads(["A"])
        f.db.sql.assert_not_called()

    @patch.object(mod,"frappe")
    def test_uninitialized_worker_fails_closed(self,f):
        f.db.get_global.return_value=0
        with self.assertRaises(RuntimeError):mod.process_due()
        f.db.sql.assert_not_called()

    @patch.object(mod,"frappe")
    def test_dry_initializer_does_not_mark_or_advance(self,f):
        f.conf={"nas_reconciliation_capture":1};f.local.site="test.local"
        f.db.get_global.side_effect=lambda key:0 if key==mod.DONE else ""
        f.db.sql.return_value=[(1,)]
        f.get_all.return_value=["A"]
        with patch.object(mod,"mark_leads") as mark:
            r=mod.initialize()
        self.assertTrue(r["dry_run"]);mark.assert_not_called()
        f.db.set_global.assert_not_called();f.db.commit.assert_not_called()

    @patch.object(mod,"frappe")
    def test_initialization_failure_does_not_advance(self,f):
        f.conf={"nas_reconciliation_capture":1};f.local.site="test.local"
        f.db.get_global.side_effect=lambda key:0 if key==mod.DONE else ""
        f.db.sql.return_value=[(1,)];f.get_all.return_value=["A"]
        with patch.object(mod,"mark_leads",side_effect=RuntimeError("write failed")):
            with self.assertRaises(RuntimeError):mod.initialize(dry_run=False)
        f.db.rollback.assert_called_once();f.db.set_global.assert_not_called()


if __name__=="__main__":unittest.main()
