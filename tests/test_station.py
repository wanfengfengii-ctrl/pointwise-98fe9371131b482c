import unittest
from contextlib import closing
from fractions import Fraction

from ledger.revisions import record_revision
from ledger.store import open_ledger
from ledger.trials import initialize_trial
from station.evidence import evaluate_boundary_evidence
from station.fit import station_check
from station.publish import decode_station_artifact, freeze_station, load_station_artifact
from tests import STATIONS, counts, exact, frozen_station, hidden_exact, ordinary, profile_rows, target_b, workdir


class StationTests(unittest.TestCase):
    def setUp(self):
        self.directory = workdir(self)
        self.path = self.directory / 'source.sqlite3'

    def register(self, db, exact_rows, observations=()):
        trial = initialize_trial(db, 'trial', 'mm', STATIONS)
        return record_revision(db, trial.trial_id, 'left', 'mm', 'r1', exact_rows, observations)

    def test_weighted_residual(self):
        with closing(open_ledger(self.path)) as db:
            revision = self.register(db, [exact('anchor', {'A': 1}, 0)],
                                     [ordinary('lo', {'B': 1}, 1), ordinary('hi', {'B': 1}, 3)])
            fit = station_check(db, revision)
            self.assertTrue(fit.feasible)
            self.assertEqual(fit.residual, Fraction(2))
            artifact = freeze_station(db, revision, ('A', 'B'))
            self.assertEqual(freeze_station(db, revision, ('A', 'B')), artifact)
            self.assertEqual(counts(db, 'station_artifacts'), (1,))
        with closing(open_ledger(self.path)) as db:
            restored = load_station_artifact(db, artifact.artifact_id)
        self.assertEqual(restored, artifact)
        self.assertEqual(restored.revision_id, revision)
        self.assertEqual(evaluate_boundary_evidence(restored.evidence, (0, 2)), Fraction(2))

    def test_hidden_exact(self):
        for label, rows in (('initial', hidden_exact('Z')), ('renamed', list(reversed(hidden_exact('Q'))))):
            with self.subTest(case=label):
                payload = frozen_station(self.directory, 'left', rows, target_b(2), name=label)
                artifact = decode_station_artifact(payload)
                self.assertEqual(artifact.terminals, ('A', 'B'))
                self.assertNotIn(b'"Z"', payload)
                self.assertNotIn(b'"Q"', payload)
                self.assertNotIn(b'"read-B"', payload)
                self.assertEqual(evaluate_boundary_evidence(artifact.evidence, (0, 1)), Fraction(1))
                self.assertIsNone(evaluate_boundary_evidence(artifact.evidence, (0, '5/2')))
                self.assertEqual(evaluate_boundary_evidence(artifact.evidence, (1, 2)), Fraction(0))

    def test_conditional_profile(self):
        with closing(open_ledger(self.path)) as db:
            revision = self.register(db, [exact('anchor', {'A': 1}, 0)], profile_rows())
            self.assertEqual(station_check(db, revision).residual, 1)
        payload = frozen_station(self.directory, 'left', [exact('anchor', {'A': 1}, 0)], profile_rows())
        evidence = decode_station_artifact(payload).evidence
        self.assertEqual(evaluate_boundary_evidence(evidence, (0, 1)), 1)
        self.assertEqual(evaluate_boundary_evidence(evidence, (0, 3)), 3)
        self.assertIsNone(evaluate_boundary_evidence(evidence, (1, 3)))

    def test_inconsistent_exact_rows(self):
        with closing(open_ledger(self.path)) as db:
            difference = {'A': -1, 'B': 1}
            revision = self.register(db, [exact('d1', difference, 1), exact('d2', difference, 2)])
            fit = station_check(db, revision)
            self.assertFalse(fit.feasible)
            self.assertIsNone(fit.residual)
            with self.assertRaisesRegex(ValueError, 'inconsistent'):
                freeze_station(db, revision, ('A', 'B'))
            self.assertEqual(counts(db, 'station_artifacts'), (0,))

    def test_invalid_terminal(self):
        with closing(open_ledger(self.path)) as db:
            revision = self.register(db, (), target_b(2))
            for names in (('A', 'missing'), ('A', 'A')):
                with self.subTest(names=names), self.assertRaises(ValueError):
                    freeze_station(db, revision, names)
            self.assertEqual(counts(db, 'station_artifacts'), (0,))
            with self.assertRaises(KeyError):
                station_check(db, 'absent')

    def test_fractional_weights_and_no_public_points(self):
        with closing(open_ledger(self.path)) as db:
            revision = self.register(db, (), [ordinary('lo', {'B': 1}, 1, '1/2'),
                                             ordinary('hi', {'B': 1}, 3, '3/2')])
            self.assertEqual(station_check(db, revision).residual, Fraction(3, 2))
            public = freeze_station(db, revision, ('B',))
            sealed = freeze_station(db, revision, ())
        self.assertEqual(evaluate_boundary_evidence(public.evidence, ('5/2',)), Fraction(3, 2))
        self.assertEqual(evaluate_boundary_evidence(sealed.evidence, ()), Fraction(3, 2))
        with self.assertRaises(ValueError):
            evaluate_boundary_evidence(public.evidence, ())
