from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from records.provenance import ReportProvenance, insert_provenance
from records.receipts import SuccessReceipt, insert_receipt

if TYPE_CHECKING:
    from review.report import ReportDraft


@dataclass(frozen=True)
class IssuedReport:
    report_id: int
    payload: bytes
    provenance: ReportProvenance
    receipt: SuccessReceipt


def initialize_archive(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY,
            payload BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS report_provenance (
            report_id INTEGER PRIMARY KEY REFERENCES reports(id),
            request_id INTEGER NOT NULL,
            first_artifact_id TEXT NOT NULL,
            second_artifact_id TEXT NOT NULL,
            FOREIGN KEY (request_id, first_artifact_id, second_artifact_id)
                REFERENCES comparison_requests(id, first_artifact_id, second_artifact_id)
        );
        CREATE TABLE IF NOT EXISTS receipts (
            report_id INTEGER PRIMARY KEY REFERENCES reports(id),
            id TEXT NOT NULL UNIQUE
        );
    ''')


def finalize_report(db, draft: ReportDraft):
    with db:
        inserted = db.execute('INSERT INTO reports (payload) VALUES (?)', (draft.payload,))
        report_id = inserted.lastrowid
        provenance = insert_provenance(db, report_id, draft.request_id, draft.artifact_ids)
        receipt = insert_receipt(db, report_id)
    return IssuedReport(report_id, draft.payload, provenance, receipt)
