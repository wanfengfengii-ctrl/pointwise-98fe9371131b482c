import json
from dataclasses import dataclass

from assembly.bindings import TerminalBindings, TerminalRef, bind_terminals, resolve_terminal
from assembly.intake import AcceptedStationPair, accept_station_pair
from assembly.references import ReferenceValue, normalize_references
from assembly.store import load_comparison_bundle, save_comparison_bundle
from ledger.units import require_name


@dataclass(frozen=True)
class ContrastRequest:
    left: TerminalRef | None
    right: TerminalRef | None
    left_index: int | None
    right_index: int | None


@dataclass(frozen=True)
class ComparisonRequest:
    request_id: int
    name: str
    pair: AcceptedStationPair
    bindings: TerminalBindings
    references: tuple[ReferenceValue, ...]
    contrasts: tuple[ContrastRequest, ...]


def _normalize_contrasts(bindings, contrasts):
    result = []
    for item in contrasts:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError('a contrast must have two operands')
        left, right = item
        left_index = None if left is None else resolve_terminal(bindings, left)
        right_index = None if right is None else resolve_terminal(bindings, right)
        result.append(ContrastRequest(
            None if left_index is None else bindings.coordinates[left_index],
            None if right_index is None else bindings.coordinates[right_index],
            left_index, right_index,
        ))
    return tuple(result)


def prepare_comparison(db, first_payload, second_payload, bindings=(), references=(), contrasts=(), *, name='comparison'):
    name = require_name(name, 'comparison name')
    pair = accept_station_pair(first_payload, second_payload)
    terminal_bindings = bind_terminals(pair, bindings)
    reference_values = normalize_references(terminal_bindings, references)
    contrast_requests = _normalize_contrasts(terminal_bindings, contrasts)
    conditions = json.dumps({
        'bindings': terminal_bindings.pairs,
        'references': [(ref.endpoint, str(ref.value)) for ref in reference_values],
        'contrasts': [(contrast.left, contrast.right) for contrast in contrast_requests],
    }, separators=(',', ':'))
    first_id, second_id = pair.artifact_ids
    return save_comparison_bundle(db, name, (first_id, first_payload),
                                  (second_id, second_payload), conditions)


def load_comparison_request(db, request_id):
    row = load_comparison_bundle(db, request_id)
    if row is None:
        raise KeyError(request_id)
    name, conditions, first_id, first_payload, second_id, second_payload = row
    pair = accept_station_pair(first_payload, second_payload)
    if pair.artifact_ids != (first_id, second_id):
        raise ValueError('stored comparison artifact identity does not match')
    body = json.loads(conditions)
    bindings = bind_terminals(pair, body['bindings'])
    return ComparisonRequest(request_id, name, pair, bindings,
                             normalize_references(bindings, body['references']),
                             _normalize_contrasts(bindings, body['contrasts']))
