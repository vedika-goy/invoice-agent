from datetime import date
from decimal import Decimal

from invoice_engine.config import SAMPLE_INVOICES_FOLDER
from invoice_engine.decision.types import ReasonCode
from invoice_engine.numbers_check.service import build_invoice_facts, check_reading_and_numbers
from invoice_engine.reading.schemas import DocumentType, InvoiceReading, ReadAmount, ReadText
from invoice_engine.utils.pdf_document import extract_pdf_text
from invoice_engine.utils.sample_invoices import build_expected_reading, load_sample_specs
from tests.factories import TEST_TODAY

SPECS = load_sample_specs()
SUMMIT_FILE_NAME = "happy_summit_packaging.pdf"


def _load_summit_reading() -> tuple[InvoiceReading, str]:
    document = next(d for d in SPECS["documents"] if d["file_name"] == SUMMIT_FILE_NAME)
    pdf_text = extract_pdf_text((SAMPLE_INVOICES_FOLDER / SUMMIT_FILE_NAME).read_bytes())
    return build_expected_reading(document, SPECS["vendors"]), pdf_text


def _check(reading: InvoiceReading, pdf_text: str | None, today: date = TEST_TODAY) -> set[ReasonCode]:
    step = check_reading_and_numbers(reading, build_invoice_facts(reading), pdf_text, today)
    return {finding.code for finding in step.findings}


def test_clean_reading_passes():
    reading, pdf_text = _load_summit_reading()
    assert _check(reading, pdf_text) == set()


def test_misread_total_is_caught_even_when_the_quote_is_real():
    reading, pdf_text = _load_summit_reading()
    misread = reading.model_copy(update={"total": ReadAmount(value=948.94, quote=reading.total.quote)})
    assert ReasonCode.QUOTE_NOT_IN_DOCUMENT in _check(misread, pdf_text)


def test_invented_value_whose_quote_is_not_in_the_pdf_is_caught():
    reading, pdf_text = _load_summit_reading()
    invented = reading.model_copy(update={"po_number": ReadText(value="PO-9999", quote="PO-9999")})
    assert ReasonCode.QUOTE_NOT_IN_DOCUMENT in _check(invented, pdf_text)


def test_line_that_does_not_multiply_out_is_caught():
    reading, _ = _load_summit_reading()
    wrong_line = reading.line_items[0].model_copy(update={"line_amount": 600.0})
    assert ReasonCode.NUMBERS_DONT_ADD_UP in _check(reading.model_copy(update={"line_items": [wrong_line, *reading.line_items[1:]]}), None)


def test_total_that_does_not_add_up_is_caught():
    reading, _ = _load_summit_reading()
    assert ReasonCode.NUMBERS_DONT_ADD_UP in _check(reading.model_copy(update={"total": ReadAmount(value=999.0, quote="$999.00")}), None)


def test_missing_number_and_date_are_named_together():
    reading, _ = _load_summit_reading()
    incomplete = reading.model_copy(update={"invoice_number": ReadText(value=None, quote=None),
                                            "invoice_date": reading.invoice_date.model_copy(update={"value": None, "quote": None})})
    step = check_reading_and_numbers(incomplete, build_invoice_facts(incomplete), None, TEST_TODAY)
    missing = [finding for finding in step.findings if finding.code == ReasonCode.MISSING_REQUIRED_FIELD]
    assert missing[0].details["missing_fields"] == "invoice number and invoice date"


def test_future_invoice_date_and_due_date_before_invoice_date_are_caught():
    reading, _ = _load_summit_reading()
    assert ReasonCode.INVOICE_DATE_IN_FUTURE in _check(reading, None, today=date(2026, 11, 1))
    backwards = reading.model_copy(update={"due_date": reading.due_date.model_copy(update={"value": date(2026, 10, 1)})})
    assert ReasonCode.DUE_DATE_BEFORE_INVOICE_DATE in _check(backwards, None)


def test_statement_is_not_an_invoice_and_skips_the_number_checks():
    reading, _ = _load_summit_reading()
    statement = reading.model_copy(update={"document_type": DocumentType.STATEMENT, "invoice_number": ReadText(value=None, quote=None)})
    assert _check(statement, None) == {ReasonCode.NOT_AN_INVOICE}


def test_two_invoices_in_one_file_need_review():
    reading, _ = _load_summit_reading()
    assert ReasonCode.MULTIPLE_INVOICES_IN_FILE in _check(reading.model_copy(update={"invoice_count_in_file": 2}), None)


def test_tax_inclusive_prices_are_converted_to_before_tax():
    document = next(d for d in SPECS["documents"] if d["file_name"] == "ec4_maple_bakery_scan_no_po.pdf")
    reading = build_expected_reading(document, SPECS["vendors"])
    facts = build_invoice_facts(reading)
    # Printed 7.04 including 8.25% tax; the PO price before tax is 6.50.
    assert abs(facts.lines[0].pre_tax_unit_price - Decimal("6.50")) < Decimal("0.01")
    assert ReasonCode.PRICES_INCLUDE_TAX in _check(reading, None)
