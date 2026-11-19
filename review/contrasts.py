from dataclasses import dataclass
from fractions import Fraction

from assembly.bindings import TerminalRef
from assembly.requests import ComparisonRequest, ContrastRequest
from review.objective import JointOptimum


@dataclass(frozen=True)
class ContrastResult:
    left: TerminalRef | None
    right: TerminalRef | None
    value: Fraction | None

    @property
    def status(self):
        return 'unknown' if self.value is None else 'confirmed'


def _difference(vector, contrast: ContrastRequest):
    left = Fraction(0) if contrast.left_index is None else vector[contrast.left_index]
    right = Fraction(0) if contrast.right_index is None else vector[contrast.right_index]
    return left - right


def confirm_contrasts(request: ComparisonRequest, optimum: JointOptimum):
    results = []
    for contrast in request.contrasts:
        varies = any(_difference(direction, contrast) for direction in optimum.space.directions)
        value = None if varies else _difference(optimum.point, contrast)
        results.append(ContrastResult(contrast.left, contrast.right, value))
    return tuple(results)
