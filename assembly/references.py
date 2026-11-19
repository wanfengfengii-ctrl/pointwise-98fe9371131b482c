from dataclasses import dataclass
from fractions import Fraction

from assembly.bindings import TerminalRef, resolve_terminal
from ledger.units import parse_rational


@dataclass(frozen=True)
class ReferenceValue:
    endpoint: TerminalRef
    index: int
    value: Fraction


def normalize_references(bindings, references):
    normalized = []
    for item in references:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError('each reference must contain a terminal reference and value')
        endpoint, value = item
        index = resolve_terminal(bindings, endpoint)
        normalized.append(ReferenceValue(bindings.coordinates[index], index, parse_rational(value)))
    return tuple(normalized)
