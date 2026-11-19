from dataclasses import dataclass
from fractions import Fraction

from assembly.requests import ComparisonRequest
from station.constraints import AffineSpace, Vector, identity_vector, solve_affine_system
from station.evidence import BoundaryEvidence
from station.fit import minimum_on_space


@dataclass(frozen=True)
class JointOptimum:
    space: AffineSpace

    @property
    def point(self):
        return self.space.origin


def station_spans(request):
    start = 0
    for artifact in request.pair.artifacts:
        stop = start + len(artifact.terminals)
        yield artifact, slice(start, stop)
        start = stop


def _embedding(size, span):
    width = span.stop - span.start
    return tuple((*identity_vector(width, index - span.start), Fraction(0))
                 for index in range(size)) + (identity_vector(width + 1, width),)


def _embed_row(row: Vector, size, span):
    return (Fraction(0),) * span.start + row + (Fraction(0),) * (size - span.stop)


def _station_conditions(evidence: BoundaryEvidence, size, span):
    return ((_embed_row(row, size, span), target) for row, target in evidence.equations)


def solve_joint_objective(request: ComparisonRequest):
    size = len(request.bindings.coordinates)
    equations = []
    for first, second in request.bindings.links:
        row = tuple(Fraction(index == first) - Fraction(index == second) for index in range(size))
        equations.append((row, Fraction(0)))
    for reference in request.references:
        equations.append((identity_vector(size, reference.index), reference.value))

    costs = []
    for artifact, span in station_spans(request):
        evidence = artifact.evidence
        equations.extend(_station_conditions(evidence, size, span))
        costs.append(evidence.cost.transform(_embedding(size, span)))

    common = solve_affine_system(size, equations)
    if common is None:
        return None
    first, second = costs
    return JointOptimum(minimum_on_space(first.plus(second), common))
