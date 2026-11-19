import unittest
from fractions import Fraction

from ledger.readings import WeightedObservation
from ledger.revisions import load_revision, record_revision
from ledger.store import open_ledger
from ledger.trials import initialize_trial
from tests import STATIONS, counts, exact, ordinary, workdir


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.db = open_ledger(workdir(self) / 'source.sqlite3')
        self.addCleanup(self.db.close)
        self.trial = initialize_trial(self.db, 'ticket-17', 'mm', STATIONS)
        self.first = record_revision(self.db, self.trial.trial_id, 'left', 'mm', 'morning',
                                     [exact('A', {'A': 1}, 0)], [ordinary('read', {'B': 1}, 2)])

    def test_initialize_again(self):
        corrected = record_revision(self.db, self.trial.trial_id, 'left', 'mm', 'correction',
                                    [exact('A', {'A': 1}, 0)],
                                    [ordinary('read', {'B': 1}, '7/3', '3/2')], parent_id=self.first)
        self.assertEqual(initialize_trial(self.db, 'ticket-17', 'mm', reversed(STATIONS)), self.trial)
        self.assertNotEqual(self.first, corrected)
        self.assertEqual(load_revision(self.db, self.first).observations[0].target, 2)
        revised = load_revision(self.db, corrected)
        self.assertEqual(revised.parent_id, self.first)
        self.assertEqual(revised.name, 'correction')
        self.assertEqual(revised.observations, (WeightedObservation(
            'read', (('B', Fraction(1)),), Fraction(7, 3), Fraction(3, 2)),))
        self.assertEqual(counts(self.db, 'trials', 'trial_stations', 'revisions'), (1, 2, 2))

    def test_zero_weight_rejected(self):
        original = load_revision(self.db, self.first)
        with self.assertRaisesRegex(ValueError, 'weight'):
            record_revision(self.db, self.trial.trial_id, 'left', 'mm', 'bad', (),
                            [ordinary('good', {'B': 1}, 3), ordinary('bad', {'B': 1}, 0, 0)],
                            parent_id=self.first)
        self.assertEqual(counts(self.db, 'revisions'), (1,))
        self.assertEqual(load_revision(self.db, self.first), original)

    def test_invalid_batch_details(self):
        other = record_revision(self.db, self.trial.trial_id, 'right', 'mm', 'right original')
        originals = [load_revision(self.db, self.first), load_revision(self.db, other)]
        cases = (
            ('duplicate row', 'mm', self.first, [exact('a', {'A': 1}, 0)],
             [ordinary('a', {'B': 1}, 2)], 'duplicate'),
            ('wrong unit', 'cm', self.first, [], [], 'trial unit'),
            ('foreign parent', 'mm', other, [], [], 'same trial and station'),
        )
        for label, unit, parent, exact_rows, observations, error in cases:
            with self.subTest(case=label):
                with self.assertRaisesRegex(ValueError, error):
                    record_revision(self.db, self.trial.trial_id, 'left', unit, 'invalid',
                                    exact_rows, observations, parent_id=parent)
                self.assertEqual(counts(self.db, 'revisions'), (2,))
                self.assertEqual([load_revision(self.db, self.first), load_revision(self.db, other)], originals)

    def test_reject_conflicting_registration_and_duplicate_revision_name(self):
        with self.assertRaises(ValueError):
            initialize_trial(self.db, 'ticket-17', 'cm', STATIONS)
        with self.assertRaises(ValueError):
            record_revision(self.db, self.trial.trial_id, 'left', 'mm', 'morning')
        self.assertEqual(counts(self.db, 'trials', 'revisions'), (1, 1))
        self.assertEqual(load_revision(self.db, self.first).observations[0].target, 2)

    def test_unknown_revision_and_inexact_numeric_input(self):
        with self.assertRaises(KeyError):
            load_revision(self.db, 'absent')
        for value in (0.1, True, '1/0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                record_revision(self.db, self.trial.trial_id, 'left', 'mm', 'invalid',
                                (), [ordinary('r', {'B': 1}, value)])
        self.assertEqual(counts(self.db, 'revisions'), (1,))
