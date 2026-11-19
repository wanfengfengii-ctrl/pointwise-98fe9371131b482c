import json
import unittest

from demo import read_samples, run_day
from tests import workdir


class WorkdayTests(unittest.TestCase):
    def test_sample_from_registration_to_late_shift(self):
        shift, correction = read_samples()
        day = run_day(workdir(self), shift, correction)
        self.assertEqual(tuple((fit.feasible, fit.residual) for fit in day.station_checks),
                         ((True, 0), (True, 0)))
        self.assertEqual(day.result.contrasts[0].value, 1)
        self.assertEqual(day.result.residuals.stations, (('north', 1), ('south', 4)))
        self.assertEqual(day.result.residuals.total, 5)
        self.assertEqual(day.result.issued.provenance.artifact_ids, day.original_artifact_ids)
        self.assertNotEqual(day.correction_artifact_id, day.original_artifact_ids[0])
        self.assertEqual(day.retrieved, day.result.issued)
        body = json.loads(day.retrieved.payload)
        self.assertEqual(body['contrasts'], [{'left': ['north', 'B'], 'right': ['north', 'A'],
                                             'status': 'confirmed', 'value': '1'}])
        self.assertEqual(body['total_residual'], '5')
