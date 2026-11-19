import json
import unittest
from contextlib import closing
from fractions import Fraction

from assembly.requests import load_comparison_request
from assembly.store import open_review_store
from station.publish import decode_station_artifact, encode_station_artifact
from tests import DIFFERENCE, LEFT_B, counts, fixed_request, frozen_station, review_store, target_b, workdir


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.directory = workdir(self)
        self.db = review_store(self, self.directory)
        self.left = frozen_station(self.directory, 'left', (), target_b(1))
        self.right = frozen_station(self.directory, 'right', (), target_b(3))

    def test_wrong_trial(self):
        other = frozen_station(self.directory, 'right', (), target_b(3), ticket='other trial')
        baseline = fixed_request(self.db, (self.left, self.right))
        original = load_comparison_request(self.db, baseline)
        with self.assertRaisesRegex(ValueError, 'same trial'):
            fixed_request(self.db, (self.left, other))
        self.assertEqual(counts(self.db, 'comparison_requests', 'accepted_artifacts'), (1, 2))
        self.assertEqual(load_comparison_request(self.db, baseline), original)

    def test_invalid_binding(self):
        for payloads, bindings in (((self.left, self.left), (('A', 'A'),)),
                                   ((self.left, self.right), (('private', 'A'),))):
            with self.subTest(bindings=bindings), self.assertRaises(ValueError):
                fixed_request(self.db, payloads, bindings=bindings)
        with self.assertRaises(ValueError):
            fixed_request(self.db, (self.left, self.right), references=((('right', 'hidden'), 0),))
        with self.assertRaises(ValueError):
            fixed_request(self.db, (self.left, self.right), contrasts=((('third', 'A'), None),))
        self.assertEqual(counts(self.db, 'comparison_requests', 'accepted_artifacts'), (0, 0))

    def test_reuse_artifacts(self):
        first = fixed_request(self.db, (self.left, self.right), name='early check')
        second = fixed_request(self.db, (self.left, self.right), name='alternative reference',
                               bindings=(('B', 'B'),), references=((('right', 'A'), '5/2'),),
                               contrasts=(LEFT_B, DIFFERENCE, LEFT_B))
        self.db.close()
        with closing(open_review_store(self.directory / 'review.sqlite3')) as reopened:
            early = load_comparison_request(reopened, first)
            alternative = load_comparison_request(reopened, second)
            self.assertNotEqual(first, second)
            self.assertEqual((early.name, alternative.name), ('early check', 'alternative reference'))
            self.assertEqual(early.bindings.pairs, (('A', 'A'), ('B', 'B')))
            self.assertEqual(alternative.bindings.pairs, (('B', 'B'),))
            self.assertEqual([ref.value for ref in early.references], [0])
            self.assertEqual([(ref.endpoint, ref.value) for ref in alternative.references],
                             [(('right', 'A'), Fraction(5, 2))])
            self.assertEqual(tuple((item.left, item.right) for item in alternative.contrasts),
                             (LEFT_B, DIFFERENCE, LEFT_B))
            self.assertEqual(early.pair.artifact_ids, alternative.pair.artifact_ids)
            for request in (early, alternative):
                self.assertEqual(tuple(encode_station_artifact(piece) for piece in request.pair.artifacts),
                                 (self.left, self.right))
            self.assertEqual(counts(reopened, 'comparison_requests', 'accepted_artifacts'), (2, 2))

    def test_tampered_artifact_rejected_without_admission(self):
        changed = json.loads(self.left)
        changed['body']['revision_id'] = decode_station_artifact(self.right).revision_id
        altered = json.dumps(changed, sort_keys=True, separators=(',', ':')).encode('ascii')
        with self.assertRaisesRegex(ValueError, 'identity'):
            fixed_request(self.db, (altered, self.right))
        self.assertEqual(counts(self.db, 'comparison_requests', 'accepted_artifacts'), (0, 0))
