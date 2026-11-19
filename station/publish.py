import hashlib
import json
from dataclasses import dataclass

from ledger.revisions import load_revision
from ledger.units import parse_rational, require_name, validate_trial_unit
from station.constraints import solve_affine_system
from station.evidence import BoundaryEvidence, project_boundary_evidence
from station.fit import Quadratic, fit_revision
from station.terminals import select_public_terminals, validate_terminal_names


@dataclass(frozen=True)
class StationArtifact:
    trial_id: str
    station: str
    revision_id: str
    unit: str
    terminals: tuple[str, ...]
    evidence: BoundaryEvidence

    @property
    def artifact_id(self):
        return _identity(_body(self))


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')


def _body(artifact):
    evidence = artifact.evidence
    return {
        'version': 1,
        'trial_id': artifact.trial_id,
        'station': artifact.station,
        'revision_id': artifact.revision_id,
        'unit': artifact.unit,
        'terminals': list(artifact.terminals),
        'exact': [[[str(value) for value in coefficients], str(target)]
                  for coefficients, target in evidence.equations],
        'gram': [[str(value) for value in row] for row in evidence.cost.gram],
    }


def _identity(body):
    return hashlib.sha256(_json_bytes(body)).hexdigest()


def encode_station_artifact(artifact):
    body = _body(artifact)
    return _json_bytes({'id': _identity(body), 'body': body})


def _array(value):
    if not isinstance(value, list):
        raise ValueError('expected an array in the station artifact')
    return value


def _rationals(values):
    return tuple(parse_rational(value) for value in _array(values))


def decode_station_artifact(payload):
    if not isinstance(payload, bytes):
        raise ValueError('station artifact payload must be bytes')
    try:
        envelope = json.loads(payload)
        body = envelope['body']
        if body['version'] != 1:
            raise ValueError('unsupported station artifact version')
        terminals = validate_terminal_names(_array(body['terminals']))
        equations = tuple((_rationals(coefficients), parse_rational(target))
                          for coefficients, target in _array(body['exact']))
        cost = Quadratic(tuple(_rationals(row) for row in _array(body['gram'])))
        size = len(terminals)
        if cost.dimension != size or not cost.is_positive_semidefinite():
            raise ValueError('invalid station residual matrix')
        if solve_affine_system(size, equations) is None:
            raise ValueError('station artifact has no feasible public values')
        artifact = StationArtifact(require_name(body['trial_id'], 'trial ID'),
                                   require_name(body['station'], 'station'),
                                   require_name(body['revision_id'], 'revision ID'),
                                   validate_trial_unit(body['unit']), terminals,
                                   BoundaryEvidence(equations, cost))
    except (KeyError, TypeError, UnicodeError, ValueError) as error:
        raise ValueError('invalid station artifact payload') from error
    if payload != encode_station_artifact(artifact):
        raise ValueError('station artifact identity or canonical encoding does not match')
    return artifact


def freeze_station(db, revision_id, terminals):
    revision = load_revision(db, revision_id)
    public = select_public_terminals(revision, terminals)
    if not fit_revision(revision).feasible:
        raise ValueError('station exact conditions are inconsistent')
    evidence = project_boundary_evidence(revision, public)
    artifact = StationArtifact(revision.trial_id, revision.station, revision_id,
                               revision.unit, public.public, evidence)
    payload = encode_station_artifact(artifact)
    with db:
        db.execute('''
            INSERT INTO station_artifacts (id, revision_id, payload) VALUES (?, ?, ?)
            ON CONFLICT(id) DO NOTHING
        ''', (artifact.artifact_id, revision_id, payload))
        stored = db.execute('SELECT payload FROM station_artifacts WHERE id = ?',
                            (artifact.artifact_id,)).fetchone()[0]
        if stored != payload:
            raise ValueError('station artifact ID already identifies different bytes')
    return artifact


def load_station_artifact(db, artifact_id):
    row = db.execute('SELECT payload FROM station_artifacts WHERE id = ?', (artifact_id,)).fetchone()
    if row is None:
        raise KeyError(artifact_id)
    artifact = decode_station_artifact(row[0])
    if artifact.artifact_id != artifact_id:
        raise ValueError('stored station artifact has a different identity')
    return artifact
