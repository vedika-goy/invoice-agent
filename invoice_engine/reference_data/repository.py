"""Vendors and PO lines: the "spreadsheet" the checks compare invoices against."""
import sqlite3
from decimal import Decimal

from invoice_engine.reference_data.schemas import PurchaseOrderLine, Vendor

VENDOR_COLUMNS = list(Vendor.model_fields)
PO_LINE_COLUMNS = list(PurchaseOrderLine.model_fields)


class ReferenceDataRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def has_reference_data(self) -> bool:
        return self._connection.execute("SELECT 1 FROM vendors LIMIT 1").fetchone() is not None

    def replace_all(self, vendors: list[Vendor], po_lines: list[PurchaseOrderLine]) -> None:
        with self._connection:
            self._connection.execute("DELETE FROM vendors")
            self._connection.execute("DELETE FROM purchase_order_lines")
            self._connection.executemany(
                f"INSERT INTO vendors ({', '.join(VENDOR_COLUMNS)}) VALUES ({', '.join('?' * len(VENDOR_COLUMNS))})",
                [_to_row(vendor.model_dump(mode="json"), VENDOR_COLUMNS) for vendor in vendors],
            )
            self._connection.executemany(
                f"INSERT INTO purchase_order_lines ({', '.join(PO_LINE_COLUMNS)}) "
                f"VALUES ({', '.join('?' * len(PO_LINE_COLUMNS))})",
                [_to_row(po_line.model_dump(mode="json"), PO_LINE_COLUMNS) for po_line in po_lines],
            )

    def list_vendors(self) -> list[Vendor]:
        rows = self._connection.execute("SELECT * FROM vendors ORDER BY vendor_id").fetchall()
        return [Vendor.model_validate(dict(row)) for row in rows]

    def list_purchase_order_lines(self) -> list[PurchaseOrderLine]:
        rows = self._connection.execute("SELECT * FROM purchase_order_lines ORDER BY po_number, po_line").fetchall()
        return [PurchaseOrderLine.model_validate(dict(row)) for row in rows]

    def log_receipt(self, po_number: str, po_line: int, quantity_received_now: Decimal) -> PurchaseOrderLine:
        """Adds a delivery to the PO line's received quantity. Raises LookupError if the line doesn't exist."""
        if quantity_received_now <= 0:
            raise ValueError(f"A receipt must be a positive quantity, got {quantity_received_now}.")
        with self._connection:
            row = self._connection.execute(
                "SELECT * FROM purchase_order_lines WHERE po_number = ? AND po_line = ?", (po_number, po_line)
            ).fetchone()
            if row is None:
                raise LookupError(f"{po_number} has no line {po_line}.")
            updated_line = PurchaseOrderLine.model_validate(dict(row))
            updated_line.quantity_received += quantity_received_now
            self._connection.execute(
                "UPDATE purchase_order_lines SET quantity_received = ? WHERE po_number = ? AND po_line = ?",
                (str(updated_line.quantity_received), po_number, po_line),
            )
        return updated_line


def _to_row(values: dict, columns: list[str]) -> tuple:
    return tuple(values[column] for column in columns)
