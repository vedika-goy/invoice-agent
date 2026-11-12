"""Loads the seed CSVs (vendors, POs, paid invoices) and resets the demo to them."""
import csv
import sqlite3
from pathlib import Path

from invoice_engine.config import SEED_DATA_FOLDER
from invoice_engine.duplicate_check.service import normalize_invoice_number
from invoice_engine.ledger.repository import LedgerRepository
from invoice_engine.ledger.schemas import LedgerInvoice, LedgerLine, LedgerSource
from invoice_engine.reference_data.repository import ReferenceDataRepository
from invoice_engine.reference_data.schemas import PurchaseOrderLine, Vendor
from invoice_engine.run_history.repository import RunHistoryRepository

VENDORS_FILE_NAME = "vendors.csv"
PURCHASE_ORDERS_FILE_NAME = "purchase_orders.csv"
INVOICE_LEDGER_FILE_NAME = "invoice_ledger.csv"


def reset_demo_data(connection: sqlite3.Connection, seed_folder: Path = SEED_DATA_FOLDER) -> None:
    """Clears every run and reloads the CSVs. Saved readings are kept, so re-running samples stays instant."""
    vendors = load_seed_vendors(seed_folder / VENDORS_FILE_NAME)
    po_lines = load_seed_purchase_order_lines(seed_folder / PURCHASE_ORDERS_FILE_NAME)
    ledger_invoices = load_seed_ledger(seed_folder / INVOICE_LEDGER_FILE_NAME)
    RunHistoryRepository(connection).delete_all_runs()
    ReferenceDataRepository(connection).replace_all(vendors, po_lines)
    LedgerRepository(connection).replace_all(ledger_invoices)


def ensure_demo_data_loaded(connection: sqlite3.Connection) -> None:
    if not ReferenceDataRepository(connection).has_reference_data():
        reset_demo_data(connection)


def load_seed_vendors(csv_path: Path) -> list[Vendor]:
    return [Vendor.model_validate(row) for row in _read_csv_rows(csv_path)]


def load_seed_purchase_order_lines(csv_path: Path) -> list[PurchaseOrderLine]:
    return [PurchaseOrderLine.model_validate(row) for row in _read_csv_rows(csv_path)]


def load_seed_ledger(csv_path: Path) -> list[LedgerInvoice]:
    """The CSV has one row per invoice line, like an AP export; rows with the same vendor and number are one invoice."""
    invoices: dict[tuple[str, str], LedgerInvoice] = {}
    for row in _read_csv_rows(csv_path):
        key = (row["vendor_id"], row["invoice_number"])
        if key not in invoices:
            invoices[key] = LedgerInvoice(
                vendor_id=row["vendor_id"],
                invoice_number=row["invoice_number"],
                invoice_number_normalized=normalize_invoice_number(row["invoice_number"]),
                invoice_date=row["invoice_date"],
                invoice_total=row["invoice_total"],
                currency=row["currency"],
                source=LedgerSource.SEED,
                run_id=None,
                status_label=f"paid on {row['paid_on']}",
                lines=[],
            )
        invoices[key].lines.append(LedgerLine(po_number=row["po_number"], po_line=row["po_line"],
                                              quantity=row["quantity"], line_amount=row["line_amount"]))
    return list(invoices.values())


def _read_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))
