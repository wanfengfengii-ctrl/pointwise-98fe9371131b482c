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


def compute_residuals(request: ComparisonRequest, optimum: JointOptimum):
    # The joint solution already satisfies each station's domain. Along every joint
    # optimal direction the two nonnegative quadratics must each be constant.
    return ResidualLedger(tuple((artifact.station, artifact.evidence.cost.evaluate(optimum.point[span]))
                                for artifact, span in station_spans(request)))
