from records.finalize import IssuedReport
from records.provenance import load_provenance
from records.receipts import load_receipt


def get_comparison(db, report_id):
    row = db.execute('SELECT payload FROM reports WHERE id = ?', (report_id,)).fetchone()
    if row is None:
        return None
    provenance = load_provenance(db, report_id)
    receipt = load_receipt(db, report_id)
    if provenance is None or receipt is None:
        raise ValueError('archived report is missing its provenance or receipt')
    return IssuedReport(report_id, row[0], provenance, receipt)
