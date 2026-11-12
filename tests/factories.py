"""Builders for test inputs, based on the seed data so tests read like the real demo."""
from datetime import date
from decimal import Decimal

from invoice_engine.config import SEED_DATA_FOLDER
from invoice_engine.demo_data.service import load_seed_purchase_order_lines, load_seed_vendors
from invoice_engine.numbers_check.schemas import InvoiceFacts, InvoiceLineFacts
from invoice_engine.reading.schemas import DocumentType
from invoice_engine.reference_data.schemas import PurchaseOrderLine, Vendor

TEST_TODAY = date(2026, 11, 12)


def load_test_vendors() -> list[Vendor]:
    return load_seed_vendors(SEED_DATA_FOLDER / "vendors.csv")


def load_test_vendor(vendor_id: str) -> Vendor:
    return next(vendor for vendor in load_test_vendors() if vendor.vendor_id == vendor_id)


def load_test_po_lines() -> list[PurchaseOrderLine]:
    return load_seed_purchase_order_lines(SEED_DATA_FOLDER / "purchase_orders.csv")


def build_test_line(line_number: int = 1, description: str = "Yellow onions, 10 lb bag", item_code: str | None = "ONI-10",
                    quantity: str = "100", unit_price: str = "4.20", pre_tax_factor: Decimal = Decimal(1)) -> InvoiceLineFacts:
    quantity_decimal, unit_price_decimal = Decimal(quantity), Decimal(unit_price)
    line_amount = (quantity_decimal * unit_price_decimal).quantize(Decimal("0.01"))
    return InvoiceLineFacts(
        line_number=line_number, description=description, item_code=item_code, quantity=quantity_decimal,
        unit_price=unit_price_decimal, line_amount=line_amount,
        pre_tax_unit_price=(unit_price_decimal * pre_tax_factor).quantize(Decimal("0.0001")),
        pre_tax_line_amount=(line_amount * pre_tax_factor).quantize(Decimal("0.01")),
    )


def build_test_facts(**overrides) -> InvoiceFacts:
    """A clean Greenfield Produce invoice for 100 bags on PO-2041, unless overridden."""
    values = {
        "document_type": DocumentType.INVOICE, "invoice_count_in_file": 1, "vendor_name": "Greenfield Produce Co.",
        "vendor_tax_id": "84-2716630", "invoice_number": "GP-20001", "invoice_date": date(2026, 11, 4),
        "due_date": date(2026, 12, 4), "po_number": "PO-2041", "currency_code": "USD", "lines": [build_test_line()],
        "subtotal": None, "tax": None, "shipping": None, "discount": None, "total": Decimal("420.00"),
        "prices_include_tax": False, "pre_tax_factor": Decimal(1), "bank_account_last4": "4821",
    }
    values.update(overrides)
    return InvoiceFacts(**values)
