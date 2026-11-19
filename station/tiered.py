from dataclasses import dataclass

from station.constraints import reduce_equations
from station.evidence import _private_substitution
from station.fit import (
    Quadratic,
    exact_equations,
    observation_cost_from_rows,
    zero_quadratic,
)


@dataclass(frozen=True)
class TieredBoundaryEvidence:
    # Public hard equations shared by both tiers.
    equations: tuple
    # Cost profiles over (free private variables, public terminals, homogeneous 1).
    control_cost: Quadratic
    production_cost: Quadratic
    free_private: int

    @property
    def public_size(self):
        return self.control_cost.dimension - self.free_private


def project_tiered_evidence(revision, terminals):
    if revision.control_ids is None:
        raise ValueError('freeze_tiered_station requires a tiered revision with control_ids')
    points = (*terminals.private, *terminals.public)
    private_count = len(terminals.private)
    reduced = reduce_equations(len(points), exact_equations(revision, points))
    if reduced is None:
        raise ValueError('station exact conditions are inconsistent')
    rows, pivots = reduced
    public_equations = tuple((row[private_count:-1], row[-1])
                             for row, pivot in zip(rows, pivots, strict=True)
                             if pivot >= private_count)
    columns, free_private = _private_substitution(len(points), private_count, rows, pivots)
    control_ids = set(revision.control_ids)
    control_rows = tuple(row for row in revision.observations if row.row_id in control_ids)
    production_rows = tuple(row for row in revision.observations if row.row_id not in control_ids)
    if control_rows:
        control_cost = observation_cost_from_rows(control_rows, points).transform(columns)
    else:
        control_cost = zero_quadratic(len(points)).transform(columns)
    if production_rows:
        production_cost = observation_cost_from_rows(production_rows, points).transform(columns)
    else:
        production_cost = zero_quadratic(len(points)).transform(columns)
    return TieredBoundaryEvidence(public_equations, control_cost, production_cost, free_private)
