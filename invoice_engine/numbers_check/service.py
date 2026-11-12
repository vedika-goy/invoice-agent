"""Step 2: check the reading against the PDF, and check that the invoice's own numbers and dates make sense."""
from datetime import date, datetime
from decimal import Decimal

from invoice_engine.decision.schemas import Finding
from invoice_engine.decision.service import build_finding
from invoice_engine.decision.types import ReasonCode
from invoice_engine.numbers_check.schemas import InvoiceFacts, InvoiceLineFacts
from invoice_engine.pipeline.schemas import StepResult
from invoice_engine.policy.config import ROUNDING_TOLERANCE_PER_LINE_USD
from invoice_engine.reading.schemas import DocumentType, InvoiceReading, ReadAmount
from invoice_engine.utils.money import (
    UNIT_PRICE_PRECISION,
    format_money,
    format_quantity,
    parse_printed_number,
    to_money,
    to_quantity,
)
from invoice_engine.utils.text_matching import keep_alphanumeric, keep_digits, normalize_for_search

NUMBERS_STEP_NUMBER = 2
NUMBERS_STEP_TITLE = "Check the reading and the numbers"
BILL_DOCUMENT_TYPES = {DocumentType.INVOICE, DocumentType.CREDIT_NOTE}
NOT_A_BILL_LABELS = {
    DocumentType.STATEMENT: "statement of account",
    DocumentType.QUOTE: "quote",
    DocumentType.PURCHASE_ORDER: "purchase order",
    DocumentType.OTHER: "document that isn't a bill",
}
# Date formats seen on invoices; a printed date that parses to a different day than the one read is a misread.
PRINTED_DATE_FORMATS = ["%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"]


def build_invoice_facts(reading: InvoiceReading) -> InvoiceFacts:
    printed_lines_total = sum((to_money(line.line_amount) for line in reading.line_items), Decimal(0))
    tax = _to_optional_money(reading.tax)
    pre_tax_factor = Decimal(1)
    if reading.prices_include_tax and tax is not None and printed_lines_total > 0:
        pre_tax_factor = (printed_lines_total - tax) / printed_lines_total
    lines = [
        InvoiceLineFacts(
            line_number=line_number,
            description=line.description,
            item_code=line.item_code,
            quantity=to_quantity(line.quantity),
            unit_price=to_money(line.unit_price),
            line_amount=to_money(line.line_amount),
            pre_tax_unit_price=(Decimal(str(line.unit_price)) * pre_tax_factor).quantize(UNIT_PRICE_PRECISION),
            pre_tax_line_amount=to_money(Decimal(str(line.line_amount)) * pre_tax_factor),
        )
        for line_number, line in enumerate(reading.line_items, start=1)
    ]
    bank_digits = keep_digits(reading.bank_account_number.value or "")
    return InvoiceFacts(
        document_type=reading.document_type,
        invoice_count_in_file=reading.invoice_count_in_file,
        vendor_name=reading.vendor_name.value,
        vendor_tax_id=reading.vendor_tax_id.value,
        invoice_number=reading.invoice_number.value,
        invoice_date=reading.invoice_date.value,
        due_date=reading.due_date.value,
        po_number=reading.po_number.value,
        currency_code=reading.currency_code.upper() if reading.currency_code else None,
        lines=lines,
        subtotal=_to_optional_money(reading.subtotal),
        tax=tax,
        shipping=_to_optional_money(reading.shipping),
        discount=_to_optional_money(reading.discount),
        total=_to_optional_money(reading.total),
        prices_include_tax=reading.prices_include_tax,
        pre_tax_factor=pre_tax_factor,
        bank_account_last4=bank_digits[-4:] if len(bank_digits) >= 4 else None,
    )


def check_reading_and_numbers(
    reading: InvoiceReading, facts: InvoiceFacts, pdf_text: str | None, today: date
) -> StepResult:
    """pdf_text is None for scans: there is no text layer to check quotes against."""
    details, findings = _check_document_type(facts)
    details.append(_check_quotes(reading, pdf_text, findings))
    if facts.document_type not in BILL_DOCUMENT_TYPES:
        return StepResult.from_findings(NUMBERS_STEP_NUMBER, NUMBERS_STEP_TITLE, details, findings)
    findings.extend(_check_required_fields(facts))
    details.extend(_check_arithmetic(facts, findings))
    findings.extend(_check_dates(facts, today))
    if facts.prices_include_tax and facts.tax is not None:
        findings.append(build_finding(ReasonCode.PRICES_INCLUDE_TAX, tax=format_money(facts.tax, facts.currency_code)))
        details.append(f"Prices include tax, so before-tax prices are the printed prices × {facts.pre_tax_factor:.4f}.")
    return StepResult.from_findings(NUMBERS_STEP_NUMBER, NUMBERS_STEP_TITLE, details, findings)


def _check_document_type(facts: InvoiceFacts) -> tuple[list[str], list[Finding]]:
    label = facts.document_type.value.replace("_", " ")
    details = [f"Document type: {label}; {facts.invoice_count_in_file} in the file."]
    findings = []
    if facts.document_type not in BILL_DOCUMENT_TYPES:
        findings.append(build_finding(ReasonCode.NOT_AN_INVOICE,
                                      document_type_label=NOT_A_BILL_LABELS[facts.document_type]))
    if facts.document_type == DocumentType.CREDIT_NOTE:
        total = format_money(facts.total, facts.currency_code) if facts.total is not None else "an unknown amount"
        findings.append(build_finding(ReasonCode.CREDIT_NOTE, total=total, vendor_name=facts.vendor_name or "the vendor"))
    if facts.invoice_count_in_file > 1:
        findings.append(build_finding(ReasonCode.MULTIPLE_INVOICES_IN_FILE,
                                      invoice_count=str(facts.invoice_count_in_file)))
    return details, findings


def _check_quotes(reading: InvoiceReading, pdf_text: str | None, findings: list[Finding]) -> str:
    """Mutates: findings (adds QUOTE_NOT_IN_DOCUMENT). Returns the step detail line."""
    if pdf_text is None:
        return "Scanned PDF: there is no text to check quotes against, so the double read stands in for this check."
    searchable_text = normalize_for_search(pdf_text)
    checked_count, unconfirmed_labels = 0, []
    for label, is_confirmed in _list_quote_checks(reading, searchable_text):
        checked_count += 1
        if not is_confirmed:
            unconfirmed_labels.append(label)
    if unconfirmed_labels:
        findings.append(build_finding(ReasonCode.QUOTE_NOT_IN_DOCUMENT, field_list=", ".join(unconfirmed_labels),
                                      measured=f"{len(unconfirmed_labels)} of {checked_count}"))
        return f"Checked {checked_count} values against the PDF text: {len(unconfirmed_labels)} not found as read."
    return f"Checked {checked_count} values against the PDF text: every one is printed exactly as read."


def _list_quote_checks(reading: InvoiceReading, searchable_text: str) -> list[tuple[str, bool]]:
    checks = []
    for label, read_text in [("vendor name", reading.vendor_name), ("tax ID", reading.vendor_tax_id),
                             ("invoice number", reading.invoice_number), ("PO number", reading.po_number),
                             ("bank account", reading.bank_account_number)]:
        if read_text.value is not None:
            is_confirmed = _is_quote_in_text(read_text.quote, searchable_text) and (
                keep_alphanumeric(read_text.value) in keep_alphanumeric(read_text.quote or ""))
            checks.append((f"{label} ({read_text.value})", is_confirmed))
    for label, read_date in [("invoice date", reading.invoice_date), ("due date", reading.due_date)]:
        if read_date.value is not None:
            is_confirmed = _is_quote_in_text(read_date.quote, searchable_text) and _does_printed_date_match(
                read_date.quote or "", read_date.value)
            checks.append((f"{label} ({read_date.value.isoformat()})", is_confirmed))
    for label, read_amount in [("subtotal", reading.subtotal), ("tax", reading.tax), ("shipping", reading.shipping),
                               ("discount", reading.discount), ("total", reading.total)]:
        if read_amount.value is not None:
            is_confirmed = _is_quote_in_text(read_amount.quote, searchable_text) and _does_printed_number_match(
                read_amount.quote or "", to_money(abs(read_amount.value)))
            checks.append((f"{label} ({read_amount.quote or read_amount.value})", is_confirmed))
    for line_number, line in enumerate(reading.line_items, start=1):
        checks.append((f"line {line_number} description", _is_quote_in_text(line.description, searchable_text)))
        for value_label, quote, value in [("quantity", line.quantity_quote, to_quantity(line.quantity)),
                                          ("unit price", line.unit_price_quote, to_money(line.unit_price)),
                                          ("amount", line.line_amount_quote, to_money(line.line_amount))]:
            is_confirmed = _is_quote_in_text(quote, searchable_text) and _does_printed_number_match(quote, value)
            checks.append((f"line {line_number} {value_label} ({quote})", is_confirmed))
    return checks


def _check_required_fields(facts: InvoiceFacts) -> list[Finding]:
    missing_fields = [label for label, value in [("invoice number", facts.invoice_number),
                                                 ("invoice date", facts.invoice_date),
                                                 ("total", facts.total)] if value is None]
    if not missing_fields:
        return []
    joined = missing_fields[0] if len(missing_fields) == 1 else ", ".join(missing_fields[:-1]) + " and " + missing_fields[-1]
    return [build_finding(ReasonCode.MISSING_REQUIRED_FIELD, missing_fields=joined)]


def _check_arithmetic(facts: InvoiceFacts, findings: list[Finding]) -> list[str]:
    """Mutates: findings (adds NUMBERS_DONT_ADD_UP). Returns the step detail lines."""
    tolerance = ROUNDING_TOLERANCE_PER_LINE_USD * max(len(facts.lines), 1)
    line_problem_count = 0
    for line in facts.lines:
        expected_amount = to_money(line.quantity * line.unit_price)
        if abs(expected_amount - line.line_amount) > ROUNDING_TOLERANCE_PER_LINE_USD:
            line_problem_count += 1
            findings.append(build_finding(
                ReasonCode.NUMBERS_DONT_ADD_UP, measured=_format_in_invoice_currency(facts, expected_amount - line.line_amount),
                limit=_format_in_invoice_currency(facts, ROUNDING_TOLERANCE_PER_LINE_USD), printed=_format_in_invoice_currency(facts, line.line_amount),
                calculation=f"Line {line.line_number}: {format_quantity(line.quantity)} × {_format_in_invoice_currency(facts, line.unit_price)} "
                            f"= {_format_in_invoice_currency(facts, expected_amount)}"))
    details = [f"{len(facts.lines) - line_problem_count} of {len(facts.lines)} line(s) multiply out "
               "(quantity × price = amount)."]
    lines_total = sum((line.line_amount for line in facts.lines), Decimal(0))
    if facts.subtotal is not None and abs(lines_total - facts.subtotal) > tolerance:
        findings.append(build_finding(ReasonCode.NUMBERS_DONT_ADD_UP, measured=_format_in_invoice_currency(facts, lines_total - facts.subtotal),
                                      calculation=f"The lines add up to {_format_in_invoice_currency(facts, lines_total)}",
                                      printed=f"a subtotal of {_format_in_invoice_currency(facts, facts.subtotal)}"))
    if facts.total is None:
        return details
    base = facts.subtotal if facts.subtotal is not None else lines_total
    parts = [_format_in_invoice_currency(facts, base)]
    expected_total = base
    if facts.tax is not None and not facts.prices_include_tax:
        expected_total += facts.tax
        parts.append(f"+ tax {_format_in_invoice_currency(facts, facts.tax)}")
    if facts.shipping is not None:
        expected_total += facts.shipping
        parts.append(f"+ shipping {_format_in_invoice_currency(facts, facts.shipping)}")
    if facts.discount is not None:
        expected_total -= facts.discount
        parts.append(f"− discount {_format_in_invoice_currency(facts, facts.discount)}")
    if len(parts) == 1:
        calculation = f"The lines add up to {_format_in_invoice_currency(facts, expected_total)}"
    else:
        calculation = f"{' '.join(parts)} = {_format_in_invoice_currency(facts, expected_total)}"
    if abs(expected_total - facts.total) > tolerance:
        findings.append(build_finding(ReasonCode.NUMBERS_DONT_ADD_UP, measured=_format_in_invoice_currency(facts, expected_total - facts.total),
                                      calculation=calculation, printed=f"a total of {_format_in_invoice_currency(facts, facts.total)}"))
    else:
        details.append(f"{calculation}, matching the printed total.")
    return details


def _check_dates(facts: InvoiceFacts, today: date) -> list[Finding]:
    findings = []
    if facts.invoice_date is not None and facts.invoice_date > today:
        findings.append(build_finding(ReasonCode.INVOICE_DATE_IN_FUTURE, invoice_date=facts.invoice_date.isoformat(),
                                      today=today.isoformat()))
    if facts.invoice_date is not None and facts.due_date is not None and facts.due_date < facts.invoice_date:
        findings.append(build_finding(ReasonCode.DUE_DATE_BEFORE_INVOICE_DATE, due_date=facts.due_date.isoformat(),
                                      invoice_date=facts.invoice_date.isoformat()))
    return findings


def _is_quote_in_text(quote: str | None, searchable_text: str) -> bool:
    return bool(quote) and normalize_for_search(quote) in searchable_text


def _does_printed_number_match(printed_text: str, value: Decimal) -> bool:
    printed_number = parse_printed_number(printed_text)
    return printed_number is not None and printed_number == abs(value)


def _does_printed_date_match(printed_text: str, value: date) -> bool:
    """True when the printed date parses to the date read, or doesn't parse with any known format."""
    parsed_dates = []
    for date_format in PRINTED_DATE_FORMATS:
        try:
            parsed_dates.append(datetime.strptime(printed_text.strip(), date_format).date())
        except ValueError:
            continue
    return not parsed_dates or value in parsed_dates


def _format_in_invoice_currency(facts: InvoiceFacts, amount: Decimal) -> str:
    return format_money(amount, facts.currency_code)


def _to_optional_money(read_amount: ReadAmount) -> Decimal | None:
    return to_money(abs(read_amount.value)) if read_amount.value is not None else None
