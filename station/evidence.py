from dataclasses import dataclass
from fractions import Fraction

from ledger.units import parse_rational
from station.constraints import Equation, dot, identity_vector, reduce_equations, solve_affine_system
from station.fit import Quadratic, exact_equations, observation_cost


@dataclass(frozen=True)
class BoundaryEvidence:
    equations: tuple[Equation, ...]
    cost: Quadratic


def _private_substitution(size, private_count, rows, pivots):
    # Pivoted private variables are functions of free private and public values.
    private_rows = {pivot: row for pivot, row in zip(pivots, rows, strict=True)
                    if pivot < private_count}
    parameters = tuple(index for index in range(size) if index not in private_rows)
    columns = []
    for parameter in parameters:
        values = tuple(-private_rows[index][parameter] if index in private_rows
                       else Fraction(index == parameter) for index in range(size))
        columns.append((*values, Fraction(0)))
    origin = tuple(private_rows[index][-1] if index in private_rows else Fraction(0)
                   for index in range(size))
    free_private = private_count - len(private_rows)
    return (*columns, (*origin, Fraction(1))), free_private


def _profile_private_cost(cost, free_private):
    if not free_private:
        return cost
    # Solve the private normal equations for each public coordinate and the constant.
    # Positive semidefiniteness puts every cross column in the private block's range.
    private_rows = cost.gram[:free_private]
    boundary_width = len(cost.gram) - free_private
    columns = []
    for index in range(boundary_width):
        solution = solve_affine_system(free_private, tuple(
            (row[:free_private], -row[free_private + index]) for row in private_rows
        ))
        if solution is None:
            raise ArithmeticError('private residual cannot be profiled')
        columns.append((*solution.origin, *identity_vector(boundary_width, index)))
    return cost.transform(tuple(columns))


def project_boundary_evidence(revision, terminals):
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
    conditional = observation_cost(revision, points).transform(columns)
    return BoundaryEvidence(public_equations, _profile_private_cost(conditional, free_private))


def evaluate_boundary_evidence(evidence, values):
    values = tuple(parse_rational(value) for value in values)
    if len(values) != evidence.cost.dimension:
        raise ValueError('use one value per public terminal in its declared order')
    if any(dot(coefficients, values) != target for coefficients, target in evidence.equations):
        return None
    return evidence.cost.evaluate(values)
