from dataclasses import dataclass
from fractions import Fraction

from assembly.requests import ComparisonRequest
from review.objective import JointOptimum, station_spans


@dataclass(frozen=True)
class ResidualLedger:
    stations: tuple[tuple[str, Fraction], ...]

    @property
    def total(self):
        return sum((residual for _, residual in self.stations), Fraction(0))


@dataclass(frozen=True)
class TieredResidualLedger:
    # Each station entry is (station name, control residual, production residual).
    stations: tuple[tuple[str, Fraction, Fraction], ...]

    @property
    def control_total(self):
        return sum((entry[1] for entry in self.stations), Fraction(0))

    @property
    def production_total(self):
        return sum((entry[2] for entry in self.stations), Fraction(0))


def compute_residuals(request: ComparisonRequest, optimum: JointOptimum):
    # The joint solution already satisfies each station's domain. Along every joint
    # optimal direction the two nonnegative quadratics must each be constant.
    return ResidualLedger(tuple((artifact.station, artifact.evidence.cost.evaluate(optimum.point[span]))
                                for artifact, span in station_spans(request)))


def compute_tiered_residuals(request: ComparisonRequest, solution):
    entries = []
    point = solution.point
    for artifact, evidence, span in solution.spans:
        block = point[span]
        entries.append((artifact.station,
                        evidence.control_cost.evaluate(block),
                        evidence.production_cost.evaluate(block)))
    return TieredResidualLedger(tuple(entries))
