"""Step 5: match the invoice to its PO (or suggest one), then check prices, received quantities, the total
billed so far and charges that aren't on the PO."""
from collections import defaultdict
from decimal import Decimal

from pydantic import BaseModel
from rapidfuzz import fuzz

from invoice_engine.decision.schemas import Finding
from invoice_engine.decision.service import build_finding
from invoice_engine.decision.types import ReasonCode
from invoice_engine.ledger.schemas import BilledToDate, LedgerLine
from invoice_engine.numbers_check.schemas import InvoiceFacts, InvoiceLineFacts
from invoice_engine.pipeline.schemas import StepResult
from invoice_engine.policy.config import (
    LINE_DESCRIPTION_MIN_SIMILARITY_PERCENT,
    PRICE_TOLERANCE_PERCENT,
    UNPLANNED_CHARGE_ALLOWANCE_USD,
)
from invoice_engine.reading.schemas import DocumentType
from invoice_engine.reference_data.schemas import PurchaseOrderLine, PurchaseOrderStatus, Vendor
from invoice_engine.utils.money import (
    build_percent_difference,
    format_money,
    format_percent,
    format_quantity,
    format_quantity_with_unit,
    to_money,
)
from invoice_engine.utils.text_matching import keep_alphanumeric, keep_digits, normalize_words

PO_STEP_NUMBER = 5
PO_STEP_TITLE = "Match the PO"
NOTHING_BILLED = BilledToDate(quantity=Decimal(0), amount=Decimal(0))


class LineMatch(BaseModel):
    invoice_line: InvoiceLineFacts
    po_line: PurchaseOrderLine | None  # None: the line isn't on the PO


class PoFit(BaseModel):
    po_number: str
    invoice_amount: Decimal  # before tax
    po_amount: Decimal  # value still unbilled on the PO
    difference_percent: Decimal


class PoMatchResult(BaseModel):
    step: StepResult
    po_number: str | None  # the PO the invoice was checked against
    billable_lines: list[LedgerLine]


def normalize_po_number(po_number: str) -> str:
    return keep_digits(po_number) or keep_alphanumeric(po_number)


def match_purchase_order(
    facts: InvoiceFacts,
    vendor: Vendor | None,
    all_po_lines: list[PurchaseOrderLine],
    vendors_by_id: dict[str, Vendor],
    billed_to_date: dict[tuple[str, int], BilledToDate],
    po_number_override: str | None,
) -> PoMatchResult:
    """billed_to_date must leave out the invoice being evaluated, so a re-run never counts it against itself."""
    if facts.document_type != DocumentType.INVOICE:
        reason = "Skipped: credit notes are set against future payments, not matched to a PO." \
            if facts.document_type == DocumentType.CREDIT_NOTE else "Skipped: not an invoice."
        return PoMatchResult(step=StepResult.skipped(PO_STEP_NUMBER, PO_STEP_TITLE, reason), po_number=None, billable_lines=[])
    if vendor is None:
        step = StepResult.skipped(PO_STEP_NUMBER, PO_STEP_TITLE, "Skipped: the vendor wasn't identified.")
        return PoMatchResult(step=step, po_number=None, billable_lines=[])
    lines_by_po_number = _group_lines_by_po_number(all_po_lines)
    requested_po_number = po_number_override or facts.po_number
    if requested_po_number is None:
        step = _suggest_po(facts, vendor, lines_by_po_number, billed_to_date)
        return PoMatchResult(step=step, po_number=None, billable_lines=[])
    po_lines = _find_po_lines(requested_po_number, lines_by_po_number)
    invalid_step = _check_po_is_valid(requested_po_number, po_lines, vendor, vendors_by_id)
    if invalid_step is not None:
        return PoMatchResult(step=invalid_step, po_number=None, billable_lines=[])
    return _check_against_po(facts, po_lines, billed_to_date, is_chosen_by_reviewer=po_number_override is not None)


def _check_po_is_valid(
    requested_po_number: str, po_lines: list[PurchaseOrderLine], vendor: Vendor, vendors_by_id: dict[str, Vendor]
) -> StepResult | None:
    if not po_lines:
        finding = build_finding(ReasonCode.PO_NOT_FOUND, po_number=requested_po_number)
        return StepResult.from_findings(PO_STEP_NUMBER, PO_STEP_TITLE, [f"Looked up {requested_po_number}: not found."], [finding])
    po_number = po_lines[0].po_number
    if po_lines[0].vendor_id != vendor.vendor_id:
        po_vendor = vendors_by_id.get(po_lines[0].vendor_id)
        finding = build_finding(ReasonCode.PO_OTHER_VENDOR, po_number=po_number, vendor_name=vendor.vendor_name,
                                po_vendor_name=po_vendor.vendor_name if po_vendor else po_lines[0].vendor_id)
        return StepResult.from_findings(PO_STEP_NUMBER, PO_STEP_TITLE, [f"{po_number} belongs to another vendor."], [finding])
    if all(line.status == PurchaseOrderStatus.CLOSED for line in po_lines):
        finding = build_finding(ReasonCode.PO_CLOSED, po_number=po_number)
        return StepResult.from_findings(PO_STEP_NUMBER, PO_STEP_TITLE, [f"{po_number} is closed."], [finding])
    return None


def _check_against_po(
    facts: InvoiceFacts,
    po_lines: list[PurchaseOrderLine],
    billed_to_date: dict[tuple[str, int], BilledToDate],
    is_chosen_by_reviewer: bool,
) -> PoMatchResult:
    po_number, po_currency = po_lines[0].po_number, po_lines[0].currency
    requester = po_lines[0].requested_by
    source = "chosen by the reviewer" if is_chosen_by_reviewer else "printed on the invoice"
    details = [f"{po_number} ({source}): open, {po_currency}, raised by {requester}."]
    findings: list[Finding] = []
    if facts.currency_code and facts.currency_code != po_currency:
        findings.append(build_finding(ReasonCode.CURRENCY_MISMATCH, invoice_currency=facts.currency_code,
                                      po_number=po_number, po_currency=po_currency))
    line_matches = _match_invoice_lines(facts.lines, po_lines)
    details.extend(_check_prices(line_matches, facts, requester, findings))
    details.extend(_check_quantities(line_matches, po_number, billed_to_date, findings))
    details.extend(_check_unplanned_charges(line_matches, facts, requester, findings))
    billable_lines = [
        LedgerLine(po_number=po_number, po_line=match.po_line.po_line, quantity=match.invoice_line.quantity,
                   line_amount=match.invoice_line.pre_tax_line_amount)
        for match in line_matches if match.po_line is not None
    ]
    step = StepResult.from_findings(PO_STEP_NUMBER, PO_STEP_TITLE, details, findings)
    return PoMatchResult(step=step, po_number=po_number, billable_lines=billable_lines)


def _check_prices(line_matches: list[LineMatch], facts: InvoiceFacts, requester: str, findings: list[Finding]) -> list[str]:
    """Mutates: findings (adds PRICE_ABOVE_PO). Compares before-tax prices, since PO prices are before tax."""
    details = []
    for match in line_matches:
        if match.po_line is None:
            continue
        invoice_line, po_line = match.invoice_line, match.po_line
        difference_percent = build_percent_difference(invoice_line.pre_tax_unit_price, po_line.unit_price)
        invoice_price = format_money(to_money(invoice_line.pre_tax_unit_price), facts.currency_code)
        po_price = format_money(po_line.unit_price, po_line.currency)
        details.append(f"Line {invoice_line.line_number} ({invoice_line.description}) → PO line {po_line.po_line}: "
                       f"{invoice_price} vs PO {po_price} ({format_percent(difference_percent, has_sign=True)}).")
        if difference_percent > PRICE_TOLERANCE_PERCENT:
            findings.append(build_finding(
                ReasonCode.PRICE_ABOVE_PO, owner_name=requester,
                measured=format_percent(difference_percent, has_sign=True), limit=format_percent(PRICE_TOLERANCE_PERCENT),
                item=invoice_line.description, invoice_price=invoice_price, unit=po_line.unit_of_measure,
                difference_percent=format_percent(difference_percent), po_price=po_price,
                limit_percent=format_percent(PRICE_TOLERANCE_PERCENT), requester=requester))
    return details


def _check_quantities(
    line_matches: list[LineMatch],
    po_number: str,
    billed_to_date: dict[tuple[str, int], BilledToDate],
    findings: list[Finding],
) -> list[str]:
    """Mutates: findings (adds PO_OVERBILLED, QUANTITY_NOT_RECEIVED).

    Quantity beyond what the PO ordered is over-billing, which receiving more can't fix, so only the part
    within the PO is compared with what was received.
    """
    details = []
    for po_line, invoice_lines in _group_matches_by_po_line(line_matches):
        billed_now = sum((line.quantity for line in invoice_lines), Decimal(0))
        billed_before = billed_to_date.get((po_number, po_line.po_line), NOTHING_BILLED).quantity
        ordered_remaining = max(po_line.quantity_ordered - billed_before, Decimal(0))
        received_remaining = max(po_line.quantity_received - billed_before, Decimal(0))
        over_quantity = billed_now - ordered_remaining
        not_received_quantity = min(billed_now, ordered_remaining) - received_remaining
        unit = po_line.unit_of_measure
        quantities = {
            "po_number": po_number, "po_line": str(po_line.po_line),
            "ordered": format_quantity_with_unit(po_line.quantity_ordered, unit),
            "received": format_quantity(po_line.quantity_received),
            "billed_before": format_quantity(billed_before), "billed_now": format_quantity(billed_now),
        }
        details.append(f"{po_number} line {po_line.po_line}: {quantities['ordered']} ordered, {quantities['received']} "
                       f"received, {quantities['billed_before']} already billed; this invoice bills {quantities['billed_now']}.")
        if over_quantity > 0:
            findings.append(build_finding(
                ReasonCode.PO_OVERBILLED, measured=format_quantity(billed_before + billed_now),
                limit=format_quantity(po_line.quantity_ordered), billed_total=format_quantity(billed_before + billed_now),
                over=format_quantity_with_unit(over_quantity, unit), **quantities))
        if not_received_quantity > 0:
            findings.append(build_finding(
                ReasonCode.QUANTITY_NOT_RECEIVED, measured=quantities["billed_now"],
                limit=f"{format_quantity(received_remaining)} received and unbilled",
                not_received=format_quantity_with_unit(not_received_quantity, unit), **quantities))
    return details


def _check_unplanned_charges(
    line_matches: list[LineMatch], facts: InvoiceFacts, requester: str, findings: list[Finding]
) -> list[str]:
    """Mutates: findings. Lines that match no PO line, plus shipping, are charges the PO didn't plan for."""
    charges = [(match.invoice_line.description, match.invoice_line.pre_tax_line_amount)
               for match in line_matches if match.po_line is None]
    if facts.shipping:
        charges.append(("Shipping", facts.shipping))
    if not charges:
        return ["Every line is on the PO, and there are no extra charges."]
    amount = sum((charge_amount for _, charge_amount in charges), Decimal(0))
    charge_names = " and ".join(name for name, _ in charges)
    values = {"charges": charge_names, "amount": format_money(amount, facts.currency_code),
              "allowance": format_money(UNPLANNED_CHARGE_ALLOWANCE_USD)}
    if amount <= UNPLANNED_CHARGE_ALLOWANCE_USD:
        findings.append(build_finding(ReasonCode.UNPLANNED_CHARGE_ALLOWED, **values))
        return [f"Not on the PO: {charge_names} ({values['amount']}), within the {values['allowance']} allowance."]
    findings.append(build_finding(ReasonCode.UNPLANNED_CHARGE_OVER_ALLOWANCE, owner_name=requester,
                                  measured=values["amount"], limit=values["allowance"], requester=requester, **values))
    return [f"Not on the PO: {charge_names} ({values['amount']}), over the {values['allowance']} allowance."]


def _suggest_po(
    facts: InvoiceFacts,
    vendor: Vendor,
    lines_by_po_number: dict[str, list[PurchaseOrderLine]],
    billed_to_date: dict[tuple[str, int], BilledToDate],
) -> StepResult:
    """Suggest a PO only when exactly one of the vendor's open POs fits every line; never approve on it."""
    candidate_po_numbers = [
        po_number for po_number, po_lines in lines_by_po_number.items()
        if po_lines[0].vendor_id == vendor.vendor_id
        and any(line.status == PurchaseOrderStatus.OPEN for line in po_lines)
        and (facts.currency_code is None or po_lines[0].currency == facts.currency_code)
    ]
    fits = [fit for po_number in candidate_po_numbers
            if (fit := _build_po_fit(facts, lines_by_po_number[po_number], billed_to_date)) is not None]
    fitting_numbers = [fit.po_number for fit in fits]
    details = [f"The invoice names no PO. Checked {len(candidate_po_numbers)} open PO(s) from {vendor.vendor_name}: "
               + _describe_fitting_pos(fitting_numbers)]
    if len(fits) == 1:
        fit = fits[0]
        finding = build_finding(
            ReasonCode.NO_PO_LIKELY_PO_FOUND, po_number=fit.po_number, line_count=str(len(facts.lines)),
            invoice_amount=format_money(fit.invoice_amount, facts.currency_code),
            po_amount=format_money(fit.po_amount), difference_percent=format_percent(fit.difference_percent))
    elif fits:
        finding = build_finding(ReasonCode.NO_PO_SEVERAL_POS_FIT, po_numbers=" and ".join(fitting_numbers))
    else:
        finding = build_finding(ReasonCode.NO_PO_NO_PO_FITS, vendor_name=vendor.vendor_name)
    return StepResult.from_findings(PO_STEP_NUMBER, PO_STEP_TITLE, details, [finding])


def _describe_fitting_pos(fitting_numbers: list[str]) -> str:
    if not fitting_numbers:
        return "none fits every line."
    if len(fitting_numbers) == 1:
        return f"{fitting_numbers[0]} fits every line."
    return f"{' and '.join(fitting_numbers)} each fit every line."


def _build_po_fit(
    facts: InvoiceFacts, po_lines: list[PurchaseOrderLine], billed_to_date: dict[tuple[str, int], BilledToDate]
) -> PoFit | None:
    """A PO fits when every invoice line matches one of its lines, within the price tolerance and the
    quantity still unbilled."""
    line_matches = _match_invoice_lines(facts.lines, po_lines)
    if not line_matches or any(match.po_line is None for match in line_matches):
        return None
    for match in line_matches:
        if build_percent_difference(match.invoice_line.pre_tax_unit_price, match.po_line.unit_price) > PRICE_TOLERANCE_PERCENT:
            return None
    po_amount = Decimal(0)
    for po_line, invoice_lines in _group_matches_by_po_line(line_matches):
        billed_before = billed_to_date.get((po_line.po_number, po_line.po_line), NOTHING_BILLED).quantity
        ordered_remaining = po_line.quantity_ordered - billed_before
        if sum((line.quantity for line in invoice_lines), Decimal(0)) > ordered_remaining:
            return None
        po_amount += ordered_remaining * po_line.unit_price
    invoice_amount = sum((match.invoice_line.pre_tax_line_amount for match in line_matches), Decimal(0))
    difference_percent = abs(build_percent_difference(invoice_amount, po_amount)) if po_amount else Decimal(0)
    return PoFit(po_number=po_lines[0].po_number, invoice_amount=invoice_amount, po_amount=to_money(po_amount),
                 difference_percent=difference_percent)


def _match_invoice_lines(invoice_lines: list[InvoiceLineFacts], po_lines: list[PurchaseOrderLine]) -> list[LineMatch]:
    """Match by item code when both have one, otherwise by the most similar description above the threshold."""
    matches = []
    for invoice_line in invoice_lines:
        matched_po_line = None
        if invoice_line.item_code:
            matched_po_line = next((po_line for po_line in po_lines
                                    if keep_alphanumeric(po_line.item_code) == keep_alphanumeric(invoice_line.item_code)), None)
        if matched_po_line is None:
            best_similarity = 0.0
            for po_line in po_lines:
                similarity = fuzz.token_sort_ratio(normalize_words(invoice_line.description), normalize_words(po_line.description))
                if similarity >= LINE_DESCRIPTION_MIN_SIMILARITY_PERCENT and similarity > best_similarity:
                    matched_po_line, best_similarity = po_line, similarity
        matches.append(LineMatch(invoice_line=invoice_line, po_line=matched_po_line))
    return matches


def _group_matches_by_po_line(line_matches: list[LineMatch]) -> list[tuple[PurchaseOrderLine, list[InvoiceLineFacts]]]:
    grouped: dict[int, tuple[PurchaseOrderLine, list[InvoiceLineFacts]]] = {}
    for match in line_matches:
        if match.po_line is not None:
            grouped.setdefault(match.po_line.po_line, (match.po_line, []))[1].append(match.invoice_line)
    return list(grouped.values())


def _group_lines_by_po_number(po_lines: list[PurchaseOrderLine]) -> dict[str, list[PurchaseOrderLine]]:
    grouped: dict[str, list[PurchaseOrderLine]] = defaultdict(list)
    for po_line in po_lines:
        grouped[po_line.po_number].append(po_line)
    return dict(grouped)


def _find_po_lines(requested_po_number: str, lines_by_po_number: dict[str, list[PurchaseOrderLine]]) -> list[PurchaseOrderLine]:
    requested_key = normalize_po_number(requested_po_number)
    for po_number, po_lines in lines_by_po_number.items():
        if normalize_po_number(po_number) == requested_key:
            return po_lines
    return []
