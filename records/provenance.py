from dataclasses import dataclass


@dataclass(frozen=True)
class ReportProvenance:
    request_id: int
    artifact_ids: tuple[str, str]


def insert_provenance(db, report_id, request_id, artifact_ids):
    first, second = artifact_ids
    db.execute('''
        INSERT INTO report_provenance (report_id, request_id, first_artifact_id, second_artifact_id)
        VALUES (?, ?, ?, ?)
    ''', (report_id, request_id, first, second))
    return ReportProvenance(request_id, (first, second))


def load_provenance(db, report_id):
    row = db.execute('''
        SELECT request_id, first_artifact_id, second_artifact_id
        FROM report_provenance WHERE report_id = ?
    ''', (report_id,)).fetchone()
    if row is None:
        return None
    request_id, first, second = row
    return ReportProvenance(request_id, (first, second))
