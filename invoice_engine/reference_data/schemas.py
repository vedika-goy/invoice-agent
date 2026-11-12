from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel


class VendorStatus(StrEnum):
    APPROVED = "approved"
    BLOCKED = "blocked"


class PurchaseOrderStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class Vendor(BaseModel):
    vendor_id: str
    vendor_name: str
    tax_id: str
    status: VendorStatus
    currency: str
    bank_account_last4: str  # only the last 4 digits are kept on file
    payment_terms_days: int
    phone_on_file: str
    remit_email: str


class PurchaseOrderLine(BaseModel):
    po_number: str
    po_line: int
    vendor_id: str
    item_code: str
    description: str
    unit_of_measure: str
    quantity_ordered: Decimal
    quantity_received: Decimal
    unit_price: Decimal  # before tax
    currency: str
    status: PurchaseOrderStatus
    requested_by: str
    po_date: date
