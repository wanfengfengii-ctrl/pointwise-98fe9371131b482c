import json
import unittest
from fractions import Fraction

from review.reconcile import JointInfeasibleError, sign_comparison
from tests import (DIFFERENCE, LEFT_B, counts, exact, fixed_request, frozen_station, hidden_exact,
                   profile_rows, review_store, target_b, workdir)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = workdir(self)

    def review_offline(self, left, right, **options):
        for station in ('left', 'right'):
            (self.directory / f'{station}.sqlite3').unlink()
        db = review_store(self, self.directory)
        return db, fixed_request(db, (left, right), **options)

    def assert_accounting(self, result, values, station_residuals, total):
        self.assertEqual(tuple(item.value for item in result.contrasts), values)
        self.assertEqual(result.residuals.stations, tuple(zip(('left', 'right'), station_residuals)))
        self.assertEqual(result.residuals.total, total)
        report = json.loads(result.issued.payload)
        self.assertEqual(report['unit'], 'mm')
        self.assertEqual(report['station_residuals'], [
            {'station': station, 'residual': str(value)}
            for station, value in zip(('left', 'right'), station_residuals)
        ])
        self.assertEqual(report['total_residual'], str(total))
        self.assertEqual([item['value'] for item in report['contrasts']],
                         [None if value is None else str(value) for value in values])
        self.assertEqual([item['status'] for item in report['contrasts']],
                         ['unknown' if value is None else 'confirmed' for value in values])

    def test_offline_weighted_join(self):
        left = frozen_station(self.directory, 'left', (), target_b(1))
        right = frozen_station(self.directory, 'right', (), target_b(3))
        db, task = self.review_offline(left, right)
        self.assert_accounting(sign_comparison(db, task), (2,), (1, 1), 2)
        self.assertEqual(counts(db, 'reports', 'receipts'), (1, 1))

    def test_hidden_exact_join(self):
        left = frozen_station(self.directory, 'left', hidden_exact(), target_b(2))
        right = frozen_station(self.directory, 'right', (), target_b(3))
        db, task = self.review_offline(left, right)
        self.assert_accounting(sign_comparison(db, task), (1,), (1, 4), 5)

    def test_profiled_station_residual(self):
        left = frozen_station(self.directory, 'left', [exact('anchor', {'A': 1}, 0)], profile_rows())
        right = frozen_station(self.directory, 'right', (), target_b(4))
        db, task = self.review_offline(left, right)
        self.assert_accounting(sign_comparison(db, task), (3,), (3, 1), 4)

    def test_incompatible_pieces(self):
        relative = {'A': -1, 'B': 1}
        left = frozen_station(self.directory, 'left', [exact('r', relative, 1)], ())
        right = frozen_station(self.directory, 'right', [exact('r', relative, 2)], ())
        db, task = self.review_offline(left, right)
        with self.assertRaises(JointInfeasibleError):
            sign_comparison(db, task)
        self.assertEqual(counts(db, 'comparison_requests', 'reports', 'report_provenance', 'receipts'),
                         (1, 0, 0, 0))

    def test_hidden_exact_conflict(self):
        left = frozen_station(self.directory, 'left', hidden_exact(), target_b(2))
        right = frozen_station(self.directory, 'right', [exact('fixed B', {'B': 1}, 2)], target_b(3))
        db, task = self.review_offline(left, right)
        with self.assertRaises(JointInfeasibleError):
            sign_comparison(db, task)
        self.assertEqual(counts(db, 'reports', 'report_provenance', 'receipts'), (0, 0, 0))

    def test_floating_reference(self):
        relative = {'A': -1, 'B': 1}
        left = frozen_station(self.directory, 'left', [exact('d', relative, 1)], ())
        right = frozen_station(self.directory, 'right', [exact('d', relative, 1)], ())
        db, task = self.review_offline(left, right, references=(), contrasts=(DIFFERENCE, LEFT_B))
        self.assert_accounting(sign_comparison(db, task), (1, None), (0, 0), 0)

    def test_ordered_repeat(self):
        relative = {'A': -1, 'B': 1}
        left = frozen_station(self.directory, 'left', hidden_exact(), ())
        right = frozen_station(self.directory, 'right', [exact('d', relative, 1)], ())
        db, task = self.review_offline(left, right, references=(), contrasts=(DIFFERENCE, LEFT_B, DIFFERENCE))
        result = sign_comparison(db, task)
        self.assert_accounting(result, (1, None, 1), (0, 0), 0)
        self.assertEqual(tuple((part.left, part.right) for part in result.contrasts),
                         (DIFFERENCE, LEFT_B, DIFFERENCE))

    def test_soft_optimum_confirms_difference_with_free_translation(self):
        from tests import ordinary

        relative = {'A': -1, 'B': 1}
        left = frozen_station(self.directory, 'left', (), [ordinary('d', relative, 1, 2)])
        right = frozen_station(self.directory, 'right', (), [ordinary('d', relative, 2)])
        db, task = self.review_offline(left, right, references=(), contrasts=(DIFFERENCE, LEFT_B))
        self.assert_accounting(sign_comparison(db, task), (Fraction(4, 3), None),
                               (Fraction(2, 9), Fraction(4, 9)), Fraction(2, 3))

    def test_unbound_same_name_and_different_terminal_orders(self):
        left = frozen_station(self.directory, 'left', (), target_b(1), terminals=('B', 'A'))
        right = frozen_station(self.directory, 'right', (), target_b(3))
        db, task = self.review_offline(left, right, bindings=(('B', 'B'),),
                                       references=((('left', 'A'), 0), (('right', 'A'), 7)),
                                       contrasts=((('right', 'A'), ('left', 'A')), DIFFERENCE))
        self.assert_accounting(sign_comparison(db, task), (7, 2), (1, 1), 2)

    def test_empty_conditions_and_empty_coordinates(self):
        left = frozen_station(self.directory, 'left', (), (), terminals=())
        right = frozen_station(self.directory, 'right', (), (), terminals=())
        db, task = self.review_offline(left, right, bindings=(), references=(), contrasts=())
        self.assert_accounting(sign_comparison(db, task), (), (0, 0), 0)
