from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from ledger.units import parse_rational, require_name


@dataclass(frozen=True)
class ExactRow:
    row_id: str
    terms: tuple[tuple[str, Fraction], ...]
    target: Fraction


@dataclass(frozen=True)
class WeightedObservation:
    row_id: str
    terms: tuple[tuple[str, Fraction], ...]
    target: Fraction
    weight: Fraction


def _parse_row(row, fields, seen):
    if not isinstance(row, Mapping) or set(row) != fields:
        raise ValueError(f'expected evidence row fields {sorted(fields)!r}')
    row_id = require_name(row['id'], 'row ID')
    if row_id in seen:
        raise ValueError(f'duplicate evidence row ID: {row_id}')
    seen.add(row_id)
    if not isinstance(row['terms'], Mapping):
        raise ValueError('terms must map point names to rational coefficients')
    terms = tuple(sorted((require_name(point, 'point'), parse_rational(coefficient))
                         for point, coefficient in row['terms'].items()))
    return row_id, terms, parse_rational(row['target'])


def parse_evidence_rows(exact_rows, observations):
    seen = set()
    fields = {'id', 'terms', 'target'}
    exact = tuple(ExactRow(*_parse_row(row, fields, seen)) for row in exact_rows)
    weighted = []
    for row in observations:
        record = _parse_row(row, fields | {'weight'}, seen)
        weight = parse_rational(row['weight'])
        if weight <= 0:
            raise ValueError('observation weight must be strictly positive')
        weighted.append(WeightedObservation(*record, weight))
    return exact, tuple(weighted)
