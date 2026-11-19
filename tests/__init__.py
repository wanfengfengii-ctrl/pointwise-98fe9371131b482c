from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from assembly.requests import prepare_comparison
from assembly.store import open_review_store
from ledger.revisions import record_revision
from ledger.store import open_ledger
from ledger.trials import initialize_trial
from station.publish import encode_station_artifact, freeze_station


STATIONS = ('left', 'right')
BINDINGS = (('A', 'A'), ('B', 'B'))
DIFFERENCE = (('left', 'B'), ('left', 'A'))
LEFT_B = (('left', 'B'), None)
REFERENCE = ((('left', 'A'), 0),)


def exact(row_id, terms, target):
    return {'id': row_id, 'terms': terms, 'target': target}


def ordinary(row_id, terms, target, weight=1):
    return {**exact(row_id, terms, target), 'weight': weight}


def workdir(case):
    directory = TemporaryDirectory()
    case.addCleanup(directory.cleanup)
    return Path(directory.name)


def review_store(case, directory):
    connection = open_review_store(directory / 'review.sqlite3')
    case.addCleanup(connection.close)
    return connection


def hidden_exact(point='Z'):
    return [exact('tie', {point: 1, 'A': -1}, 0),
            exact('step', {'B': 1, point: -1}, 1)]


def profile_rows():
    return [ordinary('private', {'Z': 1}, 1), ordinary('seam', {'B': 1, 'Z': -1}, 0),
            ordinary('reference-offset', {'A': 1}, 1)]


def target_b(value):
    return [ordinary('read-B', {'A': 0, 'B': 1}, value)]


def frozen_station(directory, station, exact_rows, observations, *, ticket='shift', terminals=('A', 'B'),
                   name='initial'):
    with closing(open_ledger(directory / f'{station}.sqlite3')) as source:
        trial = initialize_trial(source, ticket, 'mm', STATIONS)
        revision_id = record_revision(source, trial.trial_id, station, 'mm', name, exact_rows, observations)
        return encode_station_artifact(freeze_station(source, revision_id, terminals))


def fixed_request(db, payloads, *, bindings=BINDINGS, references=REFERENCE, contrasts=(DIFFERENCE,),
                  name='joint check'):
    return prepare_comparison(db, *payloads, bindings, references, contrasts, name=name)


def counts(db, *tables):
    return tuple(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in tables)
