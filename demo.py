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
from station.publish import encode_station_artifact, freeze_station


@dataclass(frozen=True)
class Workday:
    station_checks: tuple[StationFit, ...]
    original_artifact_ids: tuple[str, ...]
    result: ComparisonResult
    correction_artifact_id: str
    retrieved: IssuedReport | None


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


def main():
    shift, correction = read_samples()
    with TemporaryDirectory() as temporary:
        day = run_day(Path(temporary), shift, correction)
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


if __name__ == '__main__':
    main()
