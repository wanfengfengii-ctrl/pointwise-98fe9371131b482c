from dataclasses import dataclass
from fractions import Fraction

from assembly.requests import ComparisonRequest
from station.constraints import AffineSpace, Vector, identity_vector, solve_affine_system
from station.fit import minimum_on_space
from station.publish import TieredBoundaryEvidence


@dataclass(frozen=True)
class TieredJointSolution:
    space: AffineSpace
    spans: tuple
    public_index: tuple  # joint coordinate per request.bindings.coordinates entry

    @property
    def point(self):
        return self.space.origin


def tiered_station_spans(request):
    start = 0
    spans = []
    for artifact in request.pair.artifacts:
        evidence = artifact.evidence
        if not isinstance(evidence, TieredBoundaryEvidence):
            raise ValueError('tiered reconciliation requires version 2 station artifacts')
        width = evidence.free_private + len(artifact.terminals)
        spans.append((artifact, evidence, slice(start, start + width)))
        start += width
    return tuple(spans)


def _block_embedding(size, span):
    # Block-local columns (length block width + 1), one per joint coordinate plus
    # the shared homogeneous coordinate: the cost only depends on its own block.
    width = span.stop - span.start
    return tuple(
        (*identity_vector(width, index - span.start), Fraction(0))
        for index in range(size)
    ) + (identity_vector(width + 1, width),)


def _embed_public_row(row: Vector, size, span, free_private):
    prefix = span.start + free_private
    return ((Fraction(0),) * prefix
            + row
            + (Fraction(0),) * (size - prefix - len(row)))


def solve_tiered_objective(request: ComparisonRequest):
    spans = tiered_station_spans(request)
    size = spans[-1][2].stop
    public_index = []
    for artifact, evidence, span in spans:
        for offset, terminal in enumerate(artifact.terminals):
            public_index.append(span.start + evidence.free_private + offset)
    public_index = tuple(public_index)

    equations = []
    for first, second in request.bindings.links:
        left, right = public_index[first], public_index[second]
        equations.append((tuple(Fraction(index == left) - Fraction(index == right)
                                for index in range(size)), Fraction(0)))
    for reference in request.references:
        equations.append((identity_vector(size, public_index[reference.index]), reference.value))

    control_costs = []
    production_costs = []
    for artifact, evidence, span in spans:
        for coefficients, target in evidence.equations:
            equations.append((_embed_public_row(coefficients, size, span, evidence.free_private), target))
        embedding = _block_embedding(size, span)
        control_costs.append(evidence.control_cost.transform(embedding))
        production_costs.append(evidence.production_cost.transform(embedding))

    common = solve_affine_system(size, equations)
    if common is None:
        return None
    control_total = control_costs[0].plus(control_costs[1])
    production_total = production_costs[0].plus(production_costs[1])
    control_optimal = minimum_on_space(control_total, common)
    final_space = minimum_on_space(production_total, control_optimal)
    return TieredJointSolution(final_space, spans, public_index)
