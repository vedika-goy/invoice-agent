"""Step 4: catch the same invoice billed again, even when its number is written differently."""
import re
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from invoice_engine.decision.schemas import Finding
from invoice_engine.decision.service import build_finding
from invoice_engine.decision.types import ReasonCode
from invoice_engine.numbers_check.schemas import InvoiceFacts
from invoice_engine.pipeline.schemas import StepResult
from invoice_engine.policy.config import DUPLICATE_AMOUNT_TOLERANCE_USD, DUPLICATE_WINDOW_DAYS
from invoice_engine.reference_data.schemas import Vendor
from invoice_engine.utils.money import format_money

DUPLICATE_STEP_NUMBER = 4
DUPLICATE_STEP_TITLE = "Check for duplicates"


class KnownInvoice(BaseModel):
    """An invoice already approved, paid, or open in another run."""

    vendor_id: str
    invoice_number: str
    invoice_date: date
    total: Decimal
    status_label: str  # e.g. "paid on 2026-10-29" or "open in run 3 (needs review)"


def split_invoice_number(invoice_number: str) -> tuple[str, str]:
    """(letter prefix, number core): 'INV-00873' -> ('INV', '873'); '873' -> ('', '873')."""
    alphanumeric = re.sub(r"[^0-9A-Za-z]", "", invoice_number).upper()
    prefix_match = re.match(r"[A-Z]*", alphanumeric)
    prefix = prefix_match.group() if prefix_match else ""
    core = alphanumeric[len(prefix):] or alphanumeric
    return prefix, core.lstrip("0") or "0"


def normalize_invoice_number(invoice_number: str) -> str:
    return split_invoice_number(invoice_number)[1]


def check_duplicates(facts: InvoiceFacts, vendor: Vendor | None, known_invoices: list[KnownInvoice]) -> StepResult:
    """known_invoices must not include the invoice of the run being evaluated."""
    if vendor is None:
        return StepResult.skipped(DUPLICATE_STEP_NUMBER, DUPLICATE_STEP_TITLE,
                                  "Skipped: duplicates are checked per vendor, and the vendor wasn't identified.")
    vendor_invoices = [known for known in known_invoices if known.vendor_id == vendor.vendor_id]
    details = [f"Compared with {len(vendor_invoices)} invoice(s) from {vendor.vendor_name} already paid, approved "
               "or open."]
    findings: list[Finding] = []
    same_number_invoices = _find_same_number(facts, vendor_invoices, findings)
    if facts.invoice_number is not None:
        details.append(f"Invoice number {facts.invoice_number} compares as '{normalize_invoice_number(facts.invoice_number)}' "
                       "(prefix and leading zeros ignored).")
    if facts.total is not None and facts.invoice_date is not None:
        remaining = [known for known in vendor_invoices if known not in same_number_invoices]
        _find_same_amount(facts, remaining, findings)
        details.append(f"Looked for the same amount within {DUPLICATE_WINDOW_DAYS} days "
                       f"(±{format_money(DUPLICATE_AMOUNT_TOLERANCE_USD)}).")
    if not findings:
        details.append("No duplicate found.")
    return StepResult.from_findings(DUPLICATE_STEP_NUMBER, DUPLICATE_STEP_TITLE, details, findings)


def _find_same_number(facts: InvoiceFacts, vendor_invoices: list[KnownInvoice], findings: list[Finding]) -> list[KnownInvoice]:
    """Mutates: findings. Same number core is a confirmed duplicate, unless both numbers carry different
    letter prefixes ('A-100' vs 'B-100'), which is only a possible one."""
    if facts.invoice_number is None:
        return []
    prefix, core = split_invoice_number(facts.invoice_number)
    matches = []
    for known in vendor_invoices:
        known_prefix, known_core = split_invoice_number(known.invoice_number)
        if known_core != core:
            continue
        matches.append(known)
        if prefix and known_prefix and prefix != known_prefix:
            findings.append(_build_possible_duplicate(facts, known))
        else:
            findings.append(build_finding(
                ReasonCode.DUPLICATE_CONFIRMED, measured=f"number '{core}'", limit="must be unique per vendor",
                invoice_number=facts.invoice_number, original_invoice_number=known.invoice_number,
                original_invoice_date=known.invoice_date.isoformat(), original_status=known.status_label))
    return matches


def _find_same_amount(facts: InvoiceFacts, vendor_invoices: list[KnownInvoice], findings: list[Finding]) -> None:
    """Mutates: findings (adds POSSIBLE_DUPLICATE)."""
    for known in vendor_invoices:
        days_apart = abs((facts.invoice_date - known.invoice_date).days)
        if abs(facts.total - known.total) <= DUPLICATE_AMOUNT_TOLERANCE_USD and days_apart <= DUPLICATE_WINDOW_DAYS:
            findings.append(_build_possible_duplicate(facts, known))


def _build_possible_duplicate(facts: InvoiceFacts, known: KnownInvoice) -> Finding:
    days_apart = abs((facts.invoice_date - known.invoice_date).days) if facts.invoice_date else 0
    return build_finding(
        ReasonCode.POSSIBLE_DUPLICATE, measured=f"{days_apart} days apart",
        limit=f"within {DUPLICATE_WINDOW_DAYS} days", total=format_money(known.total),
        other_invoice_number=known.invoice_number, other_invoice_date=known.invoice_date.isoformat(),
        days_apart=str(days_apart), other_status=known.status_label)
