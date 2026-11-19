from dataclasses import dataclass


@dataclass(frozen=True)
class SuccessReceipt:
    receipt_id: str
    report_id: int


def insert_receipt(db, report_id):
    receipt = SuccessReceipt(f'comparison-receipt-{report_id}', report_id)
    db.execute('INSERT INTO receipts (report_id, id) VALUES (?, ?)',
               (receipt.report_id, receipt.receipt_id))
    return receipt


def load_receipt(db, report_id):
    row = db.execute('SELECT id, report_id FROM receipts WHERE report_id = ?', (report_id,)).fetchone()
    return None if row is None else SuccessReceipt(*row)
