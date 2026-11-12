"""The ledger of approved and paid invoices, line by line, so billed-to-date can be summed per PO line."""
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from invoice_engine.ledger.schemas import BilledToDate, LedgerInvoice, LedgerLine


class LedgerRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def replace_all(self, invoices: list[LedgerInvoice]) -> None:
        with self._connection:
            self._connection.execute("DELETE FROM ledger_invoices")
            for invoice in invoices:
                self._insert_invoice(invoice)

    def record_invoice_once(self, invoice: LedgerInvoice) -> bool:
        """Records an approval once per vendor and invoice number. Returns False when it was already recorded,
        so a double click or a re-run never counts the same invoice twice toward a PO."""
        with self._connection:
            return self._insert_invoice(invoice)

    def list_invoices(self) -> list[LedgerInvoice]:
        invoice_rows = self._connection.execute("SELECT * FROM ledger_invoices ORDER BY invoice_date").fetchall()
        lines_by_invoice_id: dict[int, list[LedgerLine]] = defaultdict(list)
        for line_row in self._connection.execute("SELECT * FROM ledger_lines").fetchall():
            lines_by_invoice_id[line_row["ledger_invoice_id"]].append(
                LedgerLine(po_number=line_row["po_number"], po_line=line_row["po_line"],
                           quantity=Decimal(line_row["quantity"]), line_amount=Decimal(line_row["line_amount"]))
            )
        invoices = []
        for row in invoice_rows:
            values = {key: row[key] for key in row.keys() if key in LedgerInvoice.model_fields}
            invoices.append(LedgerInvoice.model_validate({**values, "lines": lines_by_invoice_id[row["ledger_invoice_id"]]}))
        return invoices

    def build_billed_to_date(self, excluded_run_id: int | None) -> dict[tuple[str, int], BilledToDate]:
        """Quantity and amount billed per (PO number, PO line), leaving out the invoice of excluded_run_id."""
        rows = self._connection.execute(
            "SELECT lines.po_number, lines.po_line, lines.quantity, lines.line_amount "
            "FROM ledger_lines AS lines JOIN ledger_invoices AS invoices USING (ledger_invoice_id) "
            "WHERE invoices.run_id IS NULL OR invoices.run_id != ?",
            (excluded_run_id if excluded_run_id is not None else -1,),
        ).fetchall()
        billed: dict[tuple[str, int], BilledToDate] = {}
        for row in rows:
            key = (row["po_number"], row["po_line"])
            previous = billed.get(key, BilledToDate(quantity=Decimal(0), amount=Decimal(0)))
            billed[key] = BilledToDate(quantity=previous.quantity + Decimal(row["quantity"]),
                                       amount=previous.amount + Decimal(row["line_amount"]))
        return billed

    def _insert_invoice(self, invoice: LedgerInvoice) -> bool:
        """Requires: an open transaction."""
        cursor = self._connection.execute(
            "INSERT OR IGNORE INTO ledger_invoices (vendor_id, invoice_number, invoice_number_normalized, invoice_date, "
            "invoice_total, currency, source, run_id, status_label, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (invoice.vendor_id, invoice.invoice_number, invoice.invoice_number_normalized,
             invoice.invoice_date.isoformat(), str(invoice.invoice_total), invoice.currency, invoice.source.value,
             invoice.run_id, invoice.status_label, datetime.now(timezone.utc).isoformat()),
        )
        if cursor.rowcount == 0:
            return False
        self._connection.executemany(
            "INSERT INTO ledger_lines (ledger_invoice_id, po_number, po_line, quantity, line_amount) VALUES (?, ?, ?, ?, ?)",
            [(cursor.lastrowid, line.po_number, line.po_line, str(line.quantity), str(line.line_amount))
             for line in invoice.lines],
        )
        return True
