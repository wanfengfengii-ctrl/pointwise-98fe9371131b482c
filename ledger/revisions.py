import hashlib
import json
from dataclasses import dataclass

from ledger.readings import ExactRow, WeightedObservation, parse_evidence_rows
from ledger.store import fetch_revision_batch, insert_revision_batch
from ledger.trials import require_trial_station
from ledger.units import require_matching_unit, require_name


@dataclass(frozen=True)
class Revision:
    revision_id: str
    trial_id: str
    station: str
    unit: str
    name: str
    parent_id: str | None
    exact_rows: tuple[ExactRow, ...]
    observations: tuple[WeightedObservation, ...]

    @property
    def points(self):
        return tuple(sorted({point for row in (*self.exact_rows, *self.observations)
                             for point, _ in row.terms}))


def _encode_row(row):
    wire = {'id': row.row_id, 'terms': {point: str(value) for point, value in row.terms},
            'target': str(row.target)}
    if isinstance(row, WeightedObservation):
        wire['weight'] = str(row.weight)
    return wire


def record_revision(db, trial_id, station, unit, name, exact_rows=(), observations=(), *, parent_id=None):
    trial = require_trial_station(db, trial_id, station)
    require_matching_unit(trial.unit, unit)
    name = require_name(name, 'revision name')
    if parent_id is not None:
        parent = load_revision(db, parent_id)
        if (parent.trial_id, parent.station) != (trial_id, station):
            raise ValueError('correction parent must belong to the same trial and station')
    exact, weighted = parse_evidence_rows(exact_rows, observations)
    evidence = json.dumps({'exact': [_encode_row(row) for row in exact],
                           'ordinary': [_encode_row(row) for row in weighted]},
                          sort_keys=True, separators=(',', ':'))
    identity = json.dumps([trial_id, station, name, parent_id, evidence], separators=(',', ':'))
    revision_id = hashlib.sha256(identity.encode('ascii')).hexdigest()
    insert_revision_batch(db, revision_id, trial_id, station, name, parent_id, evidence)
    return revision_id


def load_revision(db, revision_id):
    row = fetch_revision_batch(db, require_name(revision_id, 'revision ID'))
    if row is None:
        raise KeyError(revision_id)
    *metadata, evidence = row
    wire = json.loads(evidence)
    return Revision(*metadata, *parse_evidence_rows(wire['exact'], wire['ordinary']))
