"""Invoices already approved or paid: the record that duplicate checks and billed-to-date read."""
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel


class LedgerSource(StrEnum):
    SEED = "seed"  # paid before the demo started, loaded from invoice_ledger.csv
    RUN = "run"  # approved by this app


class LedgerLine(BaseModel):
    po_number: str
    po_line: int
    quantity: Decimal
    line_amount: Decimal  # before tax


class LedgerInvoice(BaseModel):
    vendor_id: str
    invoice_number: str
    invoice_number_normalized: str
    invoice_date: date
    invoice_total: Decimal
    currency: str
    source: LedgerSource
    run_id: int | None
    status_label: str  # e.g. "paid on 2026-10-29" or "approved in run 4"
    lines: list[LedgerLine]


class BilledToDate(BaseModel):
    quantity: Decimal
    amount: Decimal
