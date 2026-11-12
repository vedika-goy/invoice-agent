"""What the AI returns when it reads a document, and how the reading was obtained.

InvoiceReading is sent to Claude as the structured-output schema, so the field descriptions are part of
the reading instructions.
"""
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

QUOTE_DESCRIPTION = "The exact text the value was read from, character for character as printed; null if absent."


class DocumentType(StrEnum):
    INVOICE = "invoice"
    CREDIT_NOTE = "credit_note"
    STATEMENT = "statement"
    QUOTE = "quote"
    PURCHASE_ORDER = "purchase_order"
    OTHER = "other"


class ReadText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str | None
    quote: str | None = Field(description=QUOTE_DESCRIPTION)


class ReadDate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: date | None
    quote: str | None = Field(description=QUOTE_DESCRIPTION)


class ReadAmount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float | None = Field(description="Positive number as printed, without currency symbols.")
    quote: str | None = Field(description=QUOTE_DESCRIPTION)


class ReadLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(description="Item description exactly as printed.")
    item_code: str | None = Field(description="Item or SKU code if printed on the line.")
    quantity: float
    quantity_quote: str = Field(description=QUOTE_DESCRIPTION)
    unit_price: float = Field(description="Price per unit as printed (including tax if the prices include tax).")
    unit_price_quote: str = Field(description=QUOTE_DESCRIPTION)
    line_amount: float
    line_amount_quote: str = Field(description=QUOTE_DESCRIPTION)


class InvoiceReading(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_type: DocumentType = Field(
        description="What the document is. A statement lists invoices and a balance; quotes and POs aren't bills."
    )
    invoice_count_in_file: int = Field(description="How many separate invoices or credit notes the file contains.")
    vendor_name: ReadText = Field(description="The company that issued the document.")
    vendor_tax_id: ReadText
    invoice_number: ReadText = Field(description="The invoice or credit note number, as printed.")
    invoice_date: ReadDate
    due_date: ReadDate
    po_number: ReadText = Field(description="The buyer's purchase order number, only if printed.")
    currency_code: str | None = Field(description="ISO 4217 code, if printed or clear from the symbol and address.")
    line_items: list[ReadLineItem]
    subtotal: ReadAmount
    tax: ReadAmount = Field(description="Tax amount printed, including tax stated as included in the prices.")
    shipping: ReadAmount = Field(description="Freight, delivery or fuel charges printed outside the item lines.")
    discount: ReadAmount
    total: ReadAmount = Field(description="The amount due (or credited, for a credit note).")
    prices_include_tax: bool = Field(description="True when the document says the item prices already include tax.")
    bank_account_number: ReadText = Field(description="The bank account payments should be sent to.")


class ReadingReport(BaseModel):
    """How a reading was obtained; shown in the step log and stored with the saved reading."""

    model_id: str
    is_scan: bool
    read_count: int  # 2 for scans: they are read twice and compared
    attempt_count: int  # Claude calls made, including the one retry for an answer that didn't fit the schema
    disagreements: list[str]  # fields on which the two readings of a scan differ
    failure: str | None
    was_reused: bool
    read_at: datetime


class ReadingResult(BaseModel):
    reading: InvoiceReading | None  # None when the document couldn't be read
    report: ReadingReport
