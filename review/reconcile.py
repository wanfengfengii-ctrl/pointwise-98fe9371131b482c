from dataclasses import dataclass

from assembly.requests import load_comparison_request
from records.finalize import IssuedReport, finalize_report
from review.contrasts import ContrastResult, confirm_contrasts, confirm_tiered_contrasts
from review.objective import solve_joint_objective
from review.report import build_report, build_tiered_report
from review.residuals import compute_residuals, compute_tiered_residuals
from review.tiered_objective import solve_tiered_objective


class JointInfeasibleError(ValueError):
    pass


@dataclass(frozen=True)
class ComparisonResult:
    issued: IssuedReport
    residuals: object
    contrasts: tuple[ContrastResult, ...]


def sign_comparison(db, request_id):
    request = load_comparison_request(db, request_id)
    if request.pair.first.version == 2:
        solution = solve_tiered_objective(request)
        if solution is None:
            raise JointInfeasibleError(
                f'comparison {request_id} has no common feasible values')
        residuals = compute_tiered_residuals(request, solution)
        contrasts = confirm_tiered_contrasts(request, solution)
        draft = build_tiered_report(request, residuals, contrasts)
    else:
        optimum = solve_joint_objective(request)
        if optimum is None:
            raise JointInfeasibleError(
                f'comparison {request_id} has no common feasible values')
        residuals = compute_residuals(request, optimum)
        contrasts = confirm_contrasts(request, optimum)
        draft = build_report(request, residuals, contrasts)
    issued = finalize_report(db, draft)
    return ComparisonResult(issued, residuals, contrasts)
