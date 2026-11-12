"""How sample documents print their values, and the reading each one should produce.

samples/build_sample_pdfs.py prints with these formats and build_expected_reading() quotes with them, so the
ground-truth quotes are exactly what is printed on the PDFs.
"""
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from invoice_engine.config import SAMPLE_SPECS_PATH
from invoice_engine.reading.schemas import (
    DocumentType,
    InvoiceReading,
    ReadAmount,
    ReadDate,
    ReadLineItem,
    ReadText,
)
from invoice_engine.utils.money import to_money

CLASSIC_LAYOUT = "classic"
SIMPLE_LAYOUT = "simple"
STATEMENT_LAYOUT = "statement"


@dataclass(frozen=True)
class SampleAmounts:
    line_amounts: list[Decimal]
    subtotal: Decimal
    tax: Decimal | None
    shipping: Decimal | None
    total: Decimal


def load_sample_specs(specs_path: Path = SAMPLE_SPECS_PATH) -> dict:
    return json.loads(specs_path.read_text(encoding="utf-8"))


def build_printed_vendor(document: dict, vendors: dict) -> dict:
    """The vendor details as printed on this document, including any per-document changes (EC-3)."""
    return {**vendors[document["vendor_id"]], **document.get("vendor_overrides", {})}


def compute_sample_amounts(document: dict) -> SampleAmounts:
    if document["layout"] == STATEMENT_LAYOUT:
        balance = sum((Decimal(entry["amount"]) for entry in document["statement_entries"]), Decimal(0))
        return SampleAmounts(line_amounts=[], subtotal=balance, tax=None, shipping=None, total=balance)
    line_amounts = [to_money(Decimal(line["quantity"]) * Decimal(line["unit_price"])) for line in document["lines"]]
    subtotal = sum(line_amounts, Decimal(0))
    shipping = Decimal(document["shipping"]) if document.get("shipping") else None
    tax = None
    if document["tax_rate_percent"] is not None:
        rate = Decimal(document["tax_rate_percent"]) / Decimal(100)
        if document["prices_include_tax"]:
            tax = to_money(subtotal - subtotal / (1 + rate))
        else:
            taxable = sum((amount for amount, line in zip(line_amounts, document["lines"], strict=True)
                           if line.get("is_taxable", True)), Decimal(0))
            tax = to_money(taxable * rate)
    total = subtotal + (shipping or 0) + (tax if tax is not None and not document["prices_include_tax"] else 0)
    return SampleAmounts(line_amounts=line_amounts, subtotal=subtotal, tax=tax, shipping=shipping, total=total)


def format_printed_money(amount: Decimal, has_symbol: bool = True) -> str:
    sign = "-" if amount < 0 else ""
    return f"{sign}{'$' if has_symbol else ''}{abs(amount):,.2f}"


def format_printed_line_money(amount: Decimal, layout: str) -> str:
    """Small-vendor invoices print line prices without a currency symbol."""
    return format_printed_money(amount, has_symbol=layout != SIMPLE_LAYOUT)


def format_printed_quantity(quantity: Decimal) -> str:
    return f"{int(quantity):,}" if quantity == quantity.to_integral_value() else f"{quantity.normalize():,}"


def format_printed_date(value: date, layout: str) -> str:
    if layout == SIMPLE_LAYOUT:
        return value.strftime("%m/%d/%Y")
    return f"{value:%B} {value.day}, {value.year}"


def build_expected_reading(document: dict, vendors: dict) -> InvoiceReading:
    """The reading a perfect reader returns for this document: what the offline self-test uses instead of Claude."""
    vendor = build_printed_vendor(document, vendors)
    layout = document["layout"]
    amounts = compute_sample_amounts(document)
    return InvoiceReading(
        document_type=DocumentType(document["document_type"]),
        invoice_count_in_file=1,
        vendor_name=ReadText(value=vendor["printed_name"], quote=vendor["printed_name"]),
        vendor_tax_id=ReadText(value=vendor["tax_id"], quote=vendor["tax_id"]),
        invoice_number=_build_read_text(document["invoice_number"]),
        invoice_date=_build_read_date(document["invoice_date"], layout),
        due_date=_build_read_date(document["due_date"], layout),
        po_number=_build_read_text(document["po_number"]),
        currency_code="USD",
        line_items=[_build_read_line(line, line_amount, layout)
                    for line, line_amount in zip(document["lines"], amounts.line_amounts, strict=True)],
        subtotal=_build_read_amount(amounts.subtotal if layout == CLASSIC_LAYOUT else None),
        tax=_build_read_amount(amounts.tax),
        shipping=_build_read_amount(amounts.shipping),
        discount=_build_read_amount(None),
        total=_build_read_amount(amounts.total),
        prices_include_tax=document["prices_include_tax"],
        bank_account_number=_build_read_text(None if document.get("hide_bank_details") else vendor["bank_account_number"]),
    )


def _build_read_line(line: dict, line_amount: Decimal, layout: str) -> ReadLineItem:
    quantity, unit_price = Decimal(line["quantity"]), Decimal(line["unit_price"])
    return ReadLineItem(
        description=line["description"],
        item_code=line["item_code"] if layout == CLASSIC_LAYOUT else None,
        quantity=float(quantity),
        quantity_quote=format_printed_quantity(quantity),
        unit_price=float(unit_price),
        unit_price_quote=format_printed_line_money(unit_price, layout),
        line_amount=float(line_amount),
        line_amount_quote=format_printed_line_money(line_amount, layout),
    )


def _build_read_text(value: str | None) -> ReadText:
    return ReadText(value=value, quote=value)


def _build_read_date(value: str | None, layout: str) -> ReadDate:
    if value is None:
        return ReadDate(value=None, quote=None)
    parsed = date.fromisoformat(value)
    return ReadDate(value=parsed, quote=format_printed_date(parsed, layout))


def _build_read_amount(amount: Decimal | None) -> ReadAmount:
    if amount is None:
        return ReadAmount(value=None, quote=None)
    return ReadAmount(value=float(abs(amount)), quote=format_printed_money(amount))
