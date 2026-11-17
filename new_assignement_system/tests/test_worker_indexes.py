from unittest import TestCase
from unittest.mock import MagicMock, patch
import frappe
from new_assignement_system.maintenance import worker_indexes as indexes


class WorkerIndexTests(TestCase):
    def rows(self, target):
        _, name, columns = indexes.TARGETS[target]
        return [frappe._dict(INDEX_NAME=name,COLUMN_NAME=c,SUB_PART=None) for c in columns]

    def test_existing_definition_is_idempotent(self):
        for target in indexes.TARGETS:
            db=MagicMock();db.sql.return_value=self.rows(target)
            with patch.object(frappe,'db',db):
                self.assertEqual(indexes.install(target,apply=True)['status'],'already_present')
            db.sql.assert_called_once()

    def test_default_only_returns_plan(self):
        db=MagicMock();db.sql.side_effect=[[frappe._dict(INDEX_NAME='PRIMARY',COLUMN_NAME='name',SUB_PART=None)], [frappe._dict(COLUMN_NAME=c) for c in indexes.TARGETS['assignment'][2]]]
        with patch.object(frappe,'db',db):
            result=indexes.install()
        self.assertEqual(result['status'],'planned')
        self.assertEqual(db.sql.call_count, 2)

    def test_mismatching_named_index_rejected(self):
        db=MagicMock();db.sql.return_value=[frappe._dict(INDEX_NAME=indexes.TARGETS['assignment'][1],COLUMN_NAME='rule',SUB_PART=None)]
        with patch.object(frappe,'db',db),self.assertRaises(ValueError):
            indexes.install(apply=True)

    def test_failed_ddl_restores_metadata_timeout(self):
        db=MagicMock();db.sql.side_effect=[
            [frappe._dict(INDEX_NAME='PRIMARY',COLUMN_NAME='name',SUB_PART=None)], [frappe._dict(COLUMN_NAME=c) for c in indexes.TARGETS['assignment'][2]], [(90,)],None,RuntimeError('busy'),None]
        with patch.object(frappe,'db',db),self.assertRaises(RuntimeError):
            indexes.install(apply=True)
        self.assertEqual(db.sql.call_args.args,('SET SESSION lock_wait_timeout=%s',(90,)))

    def test_full_length_covering_prefix_skips_redundant_index(self):
        db = MagicMock()
        db.sql.return_value = self.rows('call_uuid') + [frappe._dict(
            INDEX_NAME=indexes.TARGETS['call_uuid'][1], COLUMN_NAME='name', SUB_PART=None)]
        # An alternative name can provide a broader usable index. A conflicting
        # managed name still requires human review.
        for row in db.sql.return_value:
            row.INDEX_NAME = 'existing_broader_index'
        with patch.object(frappe, 'db', db):
            self.assertEqual(indexes.install('call_uuid')['status'], 'already_present')
        db.sql.assert_called_once()

    def test_missing_column_rejected_before_ddl(self):
        db = MagicMock()
        db.sql.side_effect = [[frappe._dict(INDEX_NAME='PRIMARY', COLUMN_NAME='name', SUB_PART=None)],
                              [frappe._dict(COLUMN_NAME='name')]]
        with patch.object(frappe, 'db', db), self.assertRaisesRegex(ValueError, 'Required columns'):
            indexes.install('call_uuid', apply=True)
        self.assertEqual(db.sql.call_count, 2)

    def test_identifiers_and_apply_flag_are_validated(self):
        for target, apply in (({}, False), ('unknown', False), ('assignment', 'false')):
            with self.subTest(target=target, apply=apply), self.assertRaises(ValueError):
                indexes.install(target, apply)
