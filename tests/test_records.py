import json
import sqlite3
import unittest
from contextlib import closing

from assembly.requests import load_comparison_request
from assembly.store import open_review_store
from ledger.revisions import load_revision, record_revision
from ledger.store import open_ledger
from records.retrieve import get_comparison
from review.reconcile import sign_comparison
from station.publish import decode_station_artifact, freeze_station
from tests import counts, fixed_request, frozen_station, review_store, target_b, workdir


class RecordsTests(unittest.TestCase):
    def setUp(self):
        self.directory = workdir(self)
        self.left = frozen_station(self.directory, 'left', (), target_b(1))
        self.right = frozen_station(self.directory, 'right', (), target_b(3))
        self.db = review_store(self, self.directory)
        self.task = fixed_request(self.db, (self.left, self.right))

    def test_commit_rollback(self):
        original = load_comparison_request(self.db, self.task)
        self.db.executescript('''
            CREATE TABLE permitted_issues (report_id INTEGER PRIMARY KEY);
            CREATE TABLE release_checks (
                report_id INTEGER REFERENCES permitted_issues(report_id) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER check_release AFTER INSERT ON receipts
            BEGIN
                INSERT INTO release_checks (report_id) VALUES (NEW.report_id);
            END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
            sign_comparison(self.db, self.task)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(counts(self.db, 'reports', 'report_provenance', 'receipts', 'release_checks'),
                         (0, 0, 0, 0))
        self.assertEqual(load_comparison_request(self.db, self.task), original)
        with closing(open_review_store(self.directory / 'review.sqlite3')) as reopened:
            self.assertEqual(counts(reopened, 'reports', 'report_provenance', 'receipts'), (0, 0, 0))
            reopened.execute('DROP TRIGGER check_release')
            result = sign_comparison(reopened, self.task)
            self.assertEqual(counts(reopened, 'reports', 'report_provenance', 'receipts'), (1, 1, 1))
            self.assertEqual(result.issued.receipt.report_id, result.issued.report_id)
            self.assertEqual(result.issued.provenance.artifact_ids, original.pair.artifact_ids)
            self.assertEqual(get_comparison(reopened, result.issued.report_id), result.issued)

    def test_read_after_source_revision(self):
        issued = sign_comparison(self.db, self.task).issued
        left = decode_station_artifact(self.left)
        right = decode_station_artifact(self.right)
        self.assertEqual(issued.provenance.artifact_ids, (left.artifact_id, right.artifact_id))
        self.assertEqual(json.loads(issued.payload)['total_residual'], '2')
        source_path = self.directory / 'left.sqlite3'
        with closing(open_ledger(source_path)) as source:
            correction = record_revision(source, left.trial_id, left.station, left.unit,
                                         'late correction', (), target_b(7), parent_id=left.revision_id)
            self.assertEqual(load_revision(source, correction).parent_id, left.revision_id)
            newer = freeze_station(source, correction, left.terminals)
            self.assertNotEqual(left.artifact_id, newer.artifact_id)
        source_path.unlink()
        (self.directory / 'right.sqlite3').unlink()
        self.db.close()
        with closing(open_review_store(self.directory / 'review.sqlite3')) as reopened:
            retrieved = get_comparison(reopened, issued.report_id)
            self.assertEqual(retrieved.payload, issued.payload)
            self.assertEqual(retrieved.provenance, issued.provenance)
            self.assertEqual(retrieved.receipt, issued.receipt)
            self.assertEqual(counts(reopened, 'reports', 'receipts'), (1, 1))

    def test_missing_report(self):
        signed = sign_comparison(self.db, self.task).issued
        self.db.close()
        with closing(open_review_store(self.directory / 'review.sqlite3')) as reopened:
            self.assertIsNone(get_comparison(reopened, signed.report_id + 999))
            self.assertEqual(counts(reopened, 'reports', 'report_provenance', 'receipts'), (1, 1, 1))
