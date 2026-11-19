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
    control_ids: tuple[str, ...] | None = None

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


def _normalize_control_ids(control_ids, observations):
    if control_ids is None:
        return None
    if isinstance(control_ids, (str, bytes)) or not isinstance(control_ids, (list, tuple)):
        raise ValueError('control_ids must be a list or tuple of ordinary observation row IDs')
    if len(control_ids) != len(set(control_ids)):
        raise ValueError('control_ids contains a repeated observation row ID')
    ordinary_ids = {row.row_id for row in observations}
    unknown = [row_id for row_id in control_ids if row_id not in ordinary_ids]
    if unknown:
        raise ValueError(f'control_ids reference unknown ordinary observation rows: {unknown!r}')
    order = {row.row_id: index for index, row in enumerate(observations)}
    return tuple(sorted(control_ids, key=order.get))


def record_revision(db, trial_id, station, unit, name, exact_rows=(), observations=(), *,
                    parent_id=None, control_ids=None):
    trial = require_trial_station(db, trial_id, station)
    require_matching_unit(trial.unit, unit)
    name = require_name(name, 'revision name')
    if parent_id is not None:
        parent = load_revision(db, parent_id)
        if (parent.trial_id, parent.station) != (trial_id, station):
            raise ValueError('correction parent must belong to the same trial and station')
    exact, weighted = parse_evidence_rows(exact_rows, observations)
    control = _normalize_control_ids(control_ids, weighted)
    evidence = json.dumps({'exact': [_encode_row(row) for row in exact],
                           'ordinary': [_encode_row(row) for row in weighted]},
                          sort_keys=True, separators=(',', ':'))
    identity_material = [trial_id, station, name, parent_id, evidence]
    if control is not None:
        identity_material.append(list(control))
    identity = json.dumps(identity_material, separators=(',', ':'))
    revision_id = hashlib.sha256(identity.encode('ascii')).hexdigest()
    control_text = None if control is None else json.dumps(list(control), separators=(',', ':'))
    insert_revision_batch(db, revision_id, trial_id, station, name, parent_id, evidence, control_text)
    return revision_id


def load_revision(db, revision_id):
    row = fetch_revision_batch(db, require_name(revision_id, 'revision ID'))
    if row is None:
        raise KeyError(revision_id)
    *metadata, evidence, control_text = row
    wire = json.loads(evidence)
    exact, weighted = parse_evidence_rows(wire['exact'], wire['ordinary'])
    control_ids = None if control_text is None else tuple(json.loads(control_text))
    return Revision(*metadata, exact, weighted, control_ids)
