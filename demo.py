import json
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from assembly.requests import prepare_comparison
from assembly.store import open_review_store
from ledger.revisions import record_revision
from ledger.store import open_ledger
from ledger.trials import initialize_trial
from records.finalize import IssuedReport
from records.retrieve import get_comparison
from review.reconcile import ComparisonResult, sign_comparison
from station.fit import StationFit, station_check
from station.publish import (
    encode_station_artifact,
    freeze_station,
    freeze_tiered_station,
)

TIERED_TICKET = "fixture-tier-check"
TIERED_UNIT = "mm"
TIERED_STATIONS = ("north", "south")
TIERED_TERMINALS = ("B",)
TIERED_BINDINGS = (("B", "B"),)
TIERED_CONTRASTS = ((("north", "B"), None),)
TIERED_NORTH_ROWS = (
    {"id": "fixture_zero", "terms": {"north_private": 1}, "target": 0, "weight": 1},
    {"id": "seam_read", "terms": {"B": 1, "north_private": -1}, "target": 0, "weight": 2},
)
TIERED_SOUTH_EXACT = ({"id": "seam_pin", "terms": {"B": 1}, "target": 1},)
TIERED_CONTROL_GROUPS = (("fixture_zero",), ("seam_read",))


@dataclass(frozen=True)
class Workday:
    station_checks: tuple[StationFit, ...]
    original_artifact_ids: tuple[str, ...]
    result: ComparisonResult
    correction_artifact_id: str
    retrieved: IssuedReport | None


@dataclass(frozen=True)
class TieredDay:
    reports: tuple
    corrected_report_id: int
    first_payload: bytes
    reopened_payload: bytes
    reopened_parents: tuple
    reopened_receipt: str


def read_samples():
    directory = Path(__file__).with_name('samples')
    return tuple(json.loads((directory / name).read_text(encoding='utf-8'))
                 for name in ('shift.json', 'correction.json'))


def run_day(directory, shift, correction):
    paths = {}
    originals = {}
    station_checks = []
    station_names = tuple(station['name'] for station in shift['stations'])
    for index, station in enumerate(shift['stations'], start=1):
        name = station['name']
        path = directory / f'source-{index}.sqlite3'
        paths[name] = path
        with closing(open_ledger(path)) as source:
            trial = initialize_trial(source, shift['ticket'], shift['unit'], station_names)
            revision = record_revision(source, trial.trial_id, name, trial.unit, station['revision'],
                                       station['exact'], station['ordinary'])
            fit = station_check(source, revision)
            if not fit.feasible:
                raise ValueError(f'{name} cannot release its revision')
            station_checks.append(fit)
            originals[name] = freeze_station(source, revision, station['terminals'])

    archive = directory / 'review.sqlite3'
    comparison = shift['comparison']
    payloads = tuple(encode_station_artifact(originals[name]) for name in station_names)
    with closing(open_review_store(archive)) as review:
        request = prepare_comparison(review, *payloads, comparison['bindings'], comparison['references'],
                                     comparison['contrasts'], name=comparison['name'])
        result = sign_comparison(review, request)

    parent = originals[correction['station']]
    with closing(open_ledger(paths[parent.station])) as source:
        trial = initialize_trial(source, shift['ticket'], shift['unit'], station_names)
        revision = record_revision(source, trial.trial_id, parent.station, parent.unit,
                                   correction['revision'], correction['exact'], correction['ordinary'],
                                   parent_id=parent.revision_id)
        replacement = freeze_station(source, revision, parent.terminals)

    with closing(open_review_store(archive)) as review:
        retrieved = get_comparison(review, result.issued.report_id)
    return Workday(tuple(station_checks), tuple(originals[name].artifact_id for name in station_names),
                   result, replacement.artifact_id, retrieved)


def run_tiered_day(directory):
    """Freeze two tiered north revisions (control group swapped) and one south revision,
    issue both reports, correct the north source, then reopen the review store and claim
    the original finalized report by its original number."""
    north_path = directory / 'tiered-north.sqlite3'
    south_path = directory / 'tiered-south.sqlite3'
    with closing(open_ledger(north_path)) as north_db:
        trial = initialize_trial(north_db, TIERED_TICKET, TIERED_UNIT, TIERED_STATIONS)
        north_payloads = []
        for ordinal, group in enumerate(TIERED_CONTROL_GROUPS, 1):
            revision = record_revision(north_db, trial.trial_id, 'north', TIERED_UNIT,
                                       f'tiered-group-{ordinal}', observations=TIERED_NORTH_ROWS,
                                       control_ids=list(group))
            north_payloads.append(
                encode_station_artifact(freeze_tiered_station(north_db, revision, TIERED_TERMINALS)))
    with closing(open_ledger(south_path)) as south_db:
        trial = initialize_trial(south_db, TIERED_TICKET, TIERED_UNIT, TIERED_STATIONS)
        south_revision = record_revision(south_db, trial.trial_id, 'south', TIERED_UNIT,
                                         'tiered-seam-reference', TIERED_SOUTH_EXACT, control_ids=[])
        south_payload = encode_station_artifact(
            freeze_tiered_station(south_db, south_revision, TIERED_TERMINALS))

    archive = directory / 'tiered-review.sqlite3'
    reports = []
    with closing(open_review_store(archive)) as review:
        for group, north in zip(TIERED_CONTROL_GROUPS, north_payloads, strict=True):
            task = prepare_comparison(review, north, south_payload, TIERED_BINDINGS,
                                      contrasts=TIERED_CONTRASTS, name=f'tiered-{group[0]}')
            result = sign_comparison(review, task)
            reports.append((group, result))
        first_report_id = reports[0][1].issued.report_id
        first_parents = reports[0][1].issued.provenance.artifact_ids
        first_payload = reports[0][1].issued.payload
        first_receipt = reports[0][1].issued.receipt

    # Correct the north source after the review store has closed its work.
    with closing(open_ledger(north_path)) as north_db:
        trial = initialize_trial(north_db, TIERED_TICKET, TIERED_UNIT, TIERED_STATIONS)
        first_revision_id = json.loads(north_payloads[0])['body']['revision_id']
        correction = record_revision(north_db, trial.trial_id, 'north', TIERED_UNIT,
                                     'late tiered correction', observations=TIERED_NORTH_ROWS,
                                     control_ids=['seam_read'], parent_id=first_revision_id)
        replacement = freeze_tiered_station(north_db, correction, TIERED_TERMINALS)
    north_path.unlink()
    south_path.unlink()

    with closing(open_review_store(archive)) as reopened:
        claimed = get_comparison(reopened, first_report_id)
    if claimed is None or claimed.payload != first_payload:
        raise AssertionError('the original tiered report could not be claimed by its number')
    if claimed.provenance.artifact_ids != first_parents or claimed.receipt != first_receipt:
        raise AssertionError('tiered provenance or receipt changed after source correction')
    return TieredDay(tuple((group, json.loads(result.issued.payload)) for group, result in reports),
                    first_report_id, first_payload, claimed.payload,
                    claimed.provenance.artifact_ids, claimed.receipt.receipt_id), replacement.artifact_id


def main():
    shift, correction = read_samples()
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        day = run_day(directory, shift, correction)
        tiered_day, tiered_replacement = run_tiered_day(directory)
    result = day.result
    actual = {
        'difference': str(result.contrasts[0].value),
        'station_residuals': [str(value) for _, value in result.residuals.stations],
        'total_residual': str(result.residuals.total),
    }
    expected = {'difference': '1', 'station_residuals': ['1', '4'], 'total_residual': '5'}
    if day.retrieved is None:
        raise AssertionError('the original report could not be retrieved')
    downstream = {
        'same_report_bytes': day.retrieved.payload == result.issued.payload,
        'original_parents': day.retrieved.provenance.artifact_ids == day.original_artifact_ids,
        'same_receipt': day.retrieved.receipt == result.issued.receipt,
        'new_source_artifact': day.correction_artifact_id != day.original_artifact_ids[0],
    }
    expected_downstream = {'same_report_bytes': True, 'original_parents': True,
                           'same_receipt': True, 'new_source_artifact': True}
    if actual != expected or downstream != expected_downstream:
        raise AssertionError({'expected': expected, 'actual': actual, 'downstream': downstream})
    print(json.dumps({'report_id': day.retrieved.report_id, 'report': json.loads(day.retrieved.payload),
                      'receipt_id': day.retrieved.receipt.receipt_id,
                      'correction_artifact_id': day.correction_artifact_id}, ensure_ascii=False))
    scenario = {
        'case_id': 'v6.hidden_exact_join',
        'input': shift,
        'expected': expected,
        'actual': actual,
        'downstream_expected': expected_downstream,
        'downstream_actual': downstream,
        'code_paths': ['station/evidence.py', 'review/objective.py', 'review/residuals.py',
                       'records/finalize.py', 'records/retrieve.py'],
        'oracle': 'A=0, Z=A and B=Z+1 imply B=1. Squaring 1-2 and 1-3 gives 1 and 4.',
    }
    print('POINTWISE_SCENARIO ' + json.dumps(scenario, separators=(',', ':')))

    tiered_summary = []
    expected_tiered = {
        'fixture_zero': {'north': ('0', '2'), 'totals': ('0', '2')},
        'seam_read': {'north': ('0', '1'), 'totals': ('0', '1')},
    }
    for group, body in tiered_day.reports:
        north = body['station_residuals'][0]
        actual_group = {
            'north': (north['control_residual'], north['production_residual']),
            'totals': (body['total_residuals']['control'], body['total_residuals']['production']),
        }
        if actual_group != expected_tiered[group[0]]:
            raise AssertionError((group, actual_group, expected_tiered[group[0]]))
        contrast = body['contrasts'][0]
        if (contrast['status'], contrast['value']) != ('confirmed', '1'):
            raise AssertionError((group, contrast))
        tiered_summary.append({'control_group': group, 'report': body})
    reopen_check = {
        'report_id': tiered_day.corrected_report_id,
        'same_bytes_after_reopen': tiered_day.reopened_payload == tiered_day.first_payload,
        'original_parent_artifact_ids': tiered_day.reopened_parents,
        'receipt_id': tiered_day.reopened_receipt,
        'correction_artifact_id': tiered_replacement,
    }
    print(json.dumps({'tiered_reports': tiered_summary,
                      'tiered_reopen_claim': reopen_check}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
