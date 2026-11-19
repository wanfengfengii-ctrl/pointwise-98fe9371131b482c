import json
from dataclasses import dataclass

from assembly.requests import ComparisonRequest
from review.contrasts import ContrastResult
from review.residuals import ResidualLedger


@dataclass(frozen=True)
class ReportDraft:
    request_id: int
    artifact_ids: tuple[str, str]
    payload: bytes


def build_report(request: ComparisonRequest, residuals: ResidualLedger,
                 contrasts: tuple[ContrastResult, ...]):
    payload = {
        'version': 1,
        'request_id': request.request_id,
        'name': request.name,
        'trial_id': request.pair.first.trial_id,
        'unit': request.pair.first.unit,
        'artifact_ids': request.pair.artifact_ids,
        'station_residuals': [{'station': station, 'residual': str(residual)}
                              for station, residual in residuals.stations],
        'total_residual': str(residuals.total),
        'contrasts': [{'left': contrast.left, 'right': contrast.right, 'status': contrast.status,
                       'value': None if contrast.value is None else str(contrast.value)}
                      for contrast in contrasts],
    }
    return ReportDraft(request.request_id, request.pair.artifact_ids,
                       json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('ascii'))
