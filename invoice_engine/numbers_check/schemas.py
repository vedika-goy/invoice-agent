"""The reading as exact numbers: what every check after step 2 works from."""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from invoice_engine.reading.schemas import DocumentType


class InvoiceLineFacts(BaseModel):
    line_number: int  # 1-based, in printed order
    description: str
    item_code: str | None
    quantity: Decimal
    unit_price: Decimal  # as printed
    line_amount: Decimal  # as printed
    pre_tax_unit_price: Decimal  # equals unit_price unless the prices include tax
    pre_tax_line_amount: Decimal


class InvoiceFacts(BaseModel):
    document_type: DocumentType
    invoice_count_in_file: int
    vendor_name: str | None
    vendor_tax_id: str | None
    invoice_number: str | None
    invoice_date: date | None
    due_date: date | None
    po_number: str | None
    currency_code: str | None
    lines: list[InvoiceLineFacts]
    subtotal: Decimal | None
    tax: Decimal | None
    shipping: Decimal | None
    discount: Decimal | None
    total: Decimal | None
    prices_include_tax: bool
    pre_tax_factor: Decimal  # multiply a tax-inclusive price by this to get the before-tax price; 1 otherwise
    bank_account_last4: str | None
