import hashlib
import json
from dataclasses import dataclass

from ledger.revisions import load_revision
from ledger.units import parse_rational, require_name, validate_trial_unit
from station.constraints import solve_affine_system
from station.evidence import BoundaryEvidence, project_boundary_evidence
from station.fit import Quadratic, fit_revision
from station.terminals import select_public_terminals, validate_terminal_names
from station.tiered import TieredBoundaryEvidence, project_tiered_evidence


@dataclass(frozen=True)
class StationArtifact:
    trial_id: str
    station: str
    revision_id: str
    unit: str
    terminals: tuple[str, ...]
    evidence: object

    @property
    def artifact_id(self):
        return _identity(_body(self))

    @property
    def version(self):
        return 2 if isinstance(self.evidence, TieredBoundaryEvidence) else 1


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')


def _quadratic_wire(cost):
    return [[str(value) for value in row] for row in cost.gram]


def _body(artifact):
    evidence = artifact.evidence
    body = {
        'trial_id': artifact.trial_id,
        'station': artifact.station,
        'revision_id': artifact.revision_id,
        'unit': artifact.unit,
        'terminals': list(artifact.terminals),
    }
    if isinstance(evidence, TieredBoundaryEvidence):
        body.update({
            'version': 2,
            'exact': [[[str(value) for value in coefficients], str(target)]
                      for coefficients, target in evidence.equations],
            'free_private': evidence.free_private,
            'control_gram': _quadratic_wire(evidence.control_cost),
            'production_gram': _quadratic_wire(evidence.production_cost),
        })
    else:
        body.update({
            'version': 1,
            'exact': [[[str(value) for value in coefficients], str(target)]
                      for coefficients, target in evidence.equations],
            'gram': _quadratic_wire(evidence.cost),
        })
    return body


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


def _quadratic(rows, size):
    cost = Quadratic(tuple(_rationals(row) for row in _array(rows)))
    if cost.dimension != size or not cost.is_positive_semidefinite():
        raise ValueError('invalid station residual matrix')
    return cost


def _decode_tiered(body, terminals, size):
    equations = tuple((_rationals(coefficients), parse_rational(target))
                      for coefficients, target in _array(body['exact']))
    free_private = body['free_private']
    if isinstance(free_private, bool) or not isinstance(free_private, int) or free_private < 0:
        raise ValueError('invalid free private count')
    block_size = free_private + size
    control_cost = _quadratic(body['control_gram'], block_size)
    production_cost = _quadratic(body['production_gram'], block_size)
    if any(len(coefficients) != size for coefficients, _ in equations):
        raise ValueError('station artifact equation has the wrong dimension')
    if solve_affine_system(size, equations) is None:
        raise ValueError('station artifact has no feasible public values')
    return TieredBoundaryEvidence(equations, control_cost, production_cost, free_private)


def decode_station_artifact(payload):
    if not isinstance(payload, bytes):
        raise ValueError('station artifact payload must be bytes')
    try:
        envelope = json.loads(payload)
        body = envelope['body']
        version = body['version']
        terminals = validate_terminal_names(_array(body['terminals']))
        size = len(terminals)
        if version == 1:
            equations = tuple((_rationals(coefficients), parse_rational(target))
                              for coefficients, target in _array(body['exact']))
            evidence = BoundaryEvidence(equations, _quadratic(body['gram'], size))
            if solve_affine_system(size, equations) is None:
                raise ValueError('station artifact has no feasible public values')
        elif version == 2:
            evidence = _decode_tiered(body, terminals, size)
        else:
            raise ValueError('unsupported station artifact version')
        artifact = StationArtifact(require_name(body['trial_id'], 'trial ID'),
                                   require_name(body['station'], 'station'),
                                   require_name(body['revision_id'], 'revision ID'),
                                   validate_trial_unit(body['unit']), terminals, evidence)
    except (KeyError, TypeError, UnicodeError, ValueError) as error:
        raise ValueError('invalid station artifact payload') from error
    if payload != encode_station_artifact(artifact):
        raise ValueError('station artifact identity or canonical encoding does not match')
    return artifact


def _store_artifact(db, revision_id, artifact):
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


def freeze_station(db, revision_id, terminals):
    revision = load_revision(db, revision_id)
    if revision.control_ids is not None:
        raise ValueError('tiered revisions must be frozen with freeze_tiered_station')
    public = select_public_terminals(revision, terminals)
    if not fit_revision(revision).feasible:
        raise ValueError('station exact conditions are inconsistent')
    evidence = project_boundary_evidence(revision, public)
    artifact = StationArtifact(revision.trial_id, revision.station, revision_id,
                               revision.unit, public.public, evidence)
    return _store_artifact(db, revision_id, artifact)


def freeze_tiered_station(db, revision_id, terminals):
    revision = load_revision(db, revision_id)
    if revision.control_ids is None:
        raise ValueError('freeze_tiered_station requires an explicit tiered revision')
    public = select_public_terminals(revision, terminals)
    if not fit_revision(revision).feasible:
        raise ValueError('station exact conditions are inconsistent')
    evidence = project_tiered_evidence(revision, public)
    artifact = StationArtifact(revision.trial_id, revision.station, revision_id,
                               revision.unit, public.public, evidence)
    return _store_artifact(db, revision_id, artifact)


def load_station_artifact(db, artifact_id):
    row = db.execute('SELECT payload FROM station_artifacts WHERE id = ?', (artifact_id,)).fetchone()
    if row is None:
        raise KeyError(artifact_id)
    artifact = decode_station_artifact(row[0])
    if artifact.artifact_id != artifact_id:
        raise ValueError('stored station artifact has a different identity')
    return artifact
