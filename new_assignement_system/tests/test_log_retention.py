import unittest
from unittest.mock import patch
from datetime import datetime
import frappe
from new_assignement_system.maintenance import log_retention as retention


class RetentionAssessmentTests(unittest.TestCase):
    def test_classification_and_no_writes(self):
        rows = [
            frappe._dict(name="a",creation="2020-01-01",status="Success",action="Assigned",queue="q"),
            frappe._dict(name="b",creation="2020-01-01",status="Success",action="Reassigned"),
            frappe._dict(name="c",creation="2020-01-01",status="Failed",action="Failed",queue="q"),
            frappe._dict(name="d",creation="2020-01-01",status="Failed",action="Failed"),
            frappe._dict(name="e",creation="2026-11-01",status="Success",action="Unassigned"),
            frappe._dict(name="f",creation=None),
        ]
        with patch.object(retention,"frappe") as fake:
            fake.get_all.return_value=rows
            result=retention.assess(90,as_of="2026-11-18")
            fake.only_for.assert_called_once_with("System Manager")
            self.assertEqual(fake.db.mock_calls,[])
            self.assertEqual(result["counts"],dict(scanned=6,old=4,recent=1,unknown_creation=1,protected_success=2,protected_queue=2,review_candidates=1))
            self.assertTrue(result["done"])
            self.assertFalse(result["deletion_enabled"])

    def test_stable_cutoff_and_bounded_cursor(self):
        with patch.object(retention,"frappe") as fake:
            fake.get_all.return_value=[frappe._dict(name="z",creation="2026-08-20")]
            result=retention.assess(90,after_name="y",batch_size=1,as_of="2026-11-18")
            self.assertFalse(result["done"])
            self.assertEqual(result["next_after_name"],"z")
            self.assertEqual(result["counts"]["recent"],1)
            self.assertEqual(fake.get_all.call_args.kwargs["filters"],{"name":[">","y"]})
            self.assertEqual(fake.get_all.call_args.kwargs["limit_page_length"],1)

    def test_bad_arguments_do_not_query(self):
        for args in [dict(keep_days=True),dict(keep_days=0),dict(keep_days="90"),dict(keep_days=90,batch_size=501),dict(keep_days=90,batch_size=True)]:
            with self.subTest(args=args),patch.object(retention,"frappe") as fake:
                with self.assertRaises(ValueError):retention.assess(**args)
                fake.get_all.assert_not_called()

    def test_permission_failure_prevents_query(self):
        with patch.object(retention,"frappe") as fake:
            fake.only_for.side_effect=PermissionError
            with self.assertRaises(PermissionError):retention.assess(90)
            fake.get_all.assert_not_called()
