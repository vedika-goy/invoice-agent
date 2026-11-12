"""Step 3: find the vendor (tax ID, then exact name, then similar name) and check its status and bank account."""
from enum import StrEnum

from pydantic import BaseModel
from rapidfuzz import fuzz

from invoice_engine.decision.schemas import Finding
from invoice_engine.decision.service import build_finding
from invoice_engine.decision.types import ReasonCode
from invoice_engine.numbers_check.schemas import InvoiceFacts
from invoice_engine.pipeline.schemas import StepResult
from invoice_engine.policy.config import VENDOR_NAME_MIN_SIMILARITY_PERCENT
from invoice_engine.reference_data.schemas import Vendor, VendorStatus
from invoice_engine.utils.text_matching import keep_digits, normalize_words

VENDOR_STEP_NUMBER = 3
VENDOR_STEP_TITLE = "Find the vendor"
# Legal-form words that vendors print inconsistently ("Co." vs "Company"); ignored when comparing names.
COMPANY_SUFFIX_WORDS = {"inc", "incorporated", "llc", "ltd", "limited", "co", "company", "corp", "corporation"}


class VendorMatchMethod(StrEnum):
    TAX_ID = "tax ID"
    EXACT_NAME = "exact name"
    SIMILAR_NAME = "similar name"


class VendorMatch(BaseModel):
    vendor: Vendor | None  # for a similar-name match, the vendor it probably is
    method: VendorMatchMethod | None
    similarity_percent: int | None


def find_vendor(facts: InvoiceFacts, vendors: list[Vendor]) -> VendorMatch:
    tax_id_digits = keep_digits(facts.vendor_tax_id or "")
    if tax_id_digits:
        for vendor in vendors:
            if keep_digits(vendor.tax_id) == tax_id_digits:
                return VendorMatch(vendor=vendor, method=VendorMatchMethod.TAX_ID, similarity_percent=None)
    if not facts.vendor_name:
        return VendorMatch(vendor=None, method=None, similarity_percent=None)
    invoice_name = _normalize_company_name(facts.vendor_name)
    best_vendor, best_similarity = None, 0
    for vendor in vendors:
        similarity = round(fuzz.ratio(invoice_name, _normalize_company_name(vendor.vendor_name)))
        if similarity == 100:
            return VendorMatch(vendor=vendor, method=VendorMatchMethod.EXACT_NAME, similarity_percent=100)
        if similarity > best_similarity:
            best_vendor, best_similarity = vendor, similarity
    if best_vendor is not None and best_similarity >= VENDOR_NAME_MIN_SIMILARITY_PERCENT:
        return VendorMatch(vendor=best_vendor, method=VendorMatchMethod.SIMILAR_NAME, similarity_percent=best_similarity)
    return VendorMatch(vendor=None, method=None, similarity_percent=None)


def check_vendor(facts: InvoiceFacts, vendor_match: VendorMatch) -> StepResult:
    vendor = vendor_match.vendor
    if vendor is None:
        finding = build_finding(ReasonCode.VENDOR_NOT_FOUND, vendor_name=facts.vendor_name or "(no vendor name)")
        details = [f"No vendor on file has tax ID {facts.vendor_tax_id or '(none printed)'} or a name like "
                   f"'{facts.vendor_name or '(none printed)'}'."]
        return StepResult.from_findings(VENDOR_STEP_NUMBER, VENDOR_STEP_TITLE, details, [finding])
    details = [f"Matched {vendor.vendor_name} ({vendor.vendor_id}) by {vendor_match.method.value}."]
    findings: list[Finding] = []
    if vendor_match.method == VendorMatchMethod.SIMILAR_NAME:
        findings.append(build_finding(
            ReasonCode.VENDOR_SIMILAR_NAME_ONLY, measured=f"{vendor_match.similarity_percent}%",
            limit="100% or a tax ID match", vendor_name=facts.vendor_name or "",
            matched_vendor_name=vendor.vendor_name, similarity=f"{vendor_match.similarity_percent}%"))
    details.append(f"Status in the vendor master: {vendor.status.value}.")
    if vendor.status == VendorStatus.BLOCKED:
        findings.append(build_finding(ReasonCode.VENDOR_BLOCKED, vendor_name=vendor.vendor_name))
    details.append(_check_bank_account(facts, vendor, findings))
    return StepResult.from_findings(VENDOR_STEP_NUMBER, VENDOR_STEP_TITLE, details, findings)


def _check_bank_account(facts: InvoiceFacts, vendor: Vendor, findings: list[Finding]) -> str:
    """Mutates: findings (adds BANK_ACCOUNT_CHANGED). Returns the step detail line."""
    if facts.bank_account_last4 is None:
        return f"No bank details on the invoice, so payment goes to the account on file (ending {vendor.bank_account_last4})."
    if facts.bank_account_last4 == vendor.bank_account_last4:
        return f"Bank account on the invoice ends {facts.bank_account_last4}, the same as on file."
    findings.append(build_finding(
        ReasonCode.BANK_ACCOUNT_CHANGED, measured=f"ends {facts.bank_account_last4}",
        limit=f"on file: ends {vendor.bank_account_last4}", invoice_last4=facts.bank_account_last4,
        file_last4=vendor.bank_account_last4, vendor_name=vendor.vendor_name, phone_on_file=vendor.phone_on_file))
    return f"Bank account on the invoice ends {facts.bank_account_last4}, but the one on file ends {vendor.bank_account_last4}."


def _normalize_company_name(name: str) -> str:
    return " ".join(word for word in normalize_words(name).split() if word not in COMPANY_SUFFIX_WORDS)
