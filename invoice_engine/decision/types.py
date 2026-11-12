"""Fixed vocabularies of a decision: outcomes, owners and reason codes."""
from enum import StrEnum


class Outcome(StrEnum):
    APPROVED = "approved"
    NEEDS_REVIEW = "needs_review"
    ON_HOLD = "on_hold"
    REJECTED = "rejected"


# When several rules fire, the outcome with the highest rank wins.
OUTCOME_SEVERITY_RANK: dict[Outcome, int] = {
    Outcome.APPROVED: 0,
    Outcome.NEEDS_REVIEW: 1,
    Outcome.ON_HOLD: 2,
    Outcome.REJECTED: 3,
}

OUTCOME_LABELS: dict[Outcome, str] = {
    Outcome.APPROVED: "Approved",
    Outcome.NEEDS_REVIEW: "Needs review",
    Outcome.ON_HOLD: "On hold",
    Outcome.REJECTED: "Rejected",
}


class Owner(StrEnum):
    AP_CLERK = "AP clerk"
    AP_MANAGER = "AP manager"
    TREASURY = "Treasury"
    RECEIVING = "Receiving"
    PROCUREMENT = "Procurement"
    VENDOR_MASTER_TEAM = "Vendor master team"
    PO_REQUESTER = "Whoever raised the PO"


class ReasonCode(StrEnum):
    # --- Rejected ---
    NOT_AN_INVOICE = "NOT_AN_INVOICE"
    DUPLICATE_CONFIRMED = "DUPLICATE_CONFIRMED"
    VENDOR_BLOCKED = "VENDOR_BLOCKED"
    # --- On hold ---
    BANK_ACCOUNT_CHANGED = "BANK_ACCOUNT_CHANGED"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    QUANTITY_NOT_RECEIVED = "QUANTITY_NOT_RECEIVED"
    # --- Needs review ---
    READING_FAILED = "READING_FAILED"
    QUOTE_NOT_IN_DOCUMENT = "QUOTE_NOT_IN_DOCUMENT"
    SCAN_READINGS_DISAGREE = "SCAN_READINGS_DISAGREE"
    MULTIPLE_INVOICES_IN_FILE = "MULTIPLE_INVOICES_IN_FILE"
    CREDIT_NOTE = "CREDIT_NOTE"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    VENDOR_NOT_FOUND = "VENDOR_NOT_FOUND"
    VENDOR_SIMILAR_NAME_ONLY = "VENDOR_SIMILAR_NAME_ONLY"
    NO_PO_LIKELY_PO_FOUND = "NO_PO_LIKELY_PO_FOUND"
    NO_PO_SEVERAL_POS_FIT = "NO_PO_SEVERAL_POS_FIT"
    NO_PO_NO_PO_FITS = "NO_PO_NO_PO_FITS"
    PO_NOT_FOUND = "PO_NOT_FOUND"
    PO_OTHER_VENDOR = "PO_OTHER_VENDOR"
    PO_CLOSED = "PO_CLOSED"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    PRICE_ABOVE_PO = "PRICE_ABOVE_PO"
    UNPLANNED_CHARGE_OVER_ALLOWANCE = "UNPLANNED_CHARGE_OVER_ALLOWANCE"
    PO_OVERBILLED = "PO_OVERBILLED"
    NUMBERS_DONT_ADD_UP = "NUMBERS_DONT_ADD_UP"
    INVOICE_DATE_IN_FUTURE = "INVOICE_DATE_IN_FUTURE"
    DUE_DATE_BEFORE_INVOICE_DATE = "DUE_DATE_BEFORE_INVOICE_DATE"
    OVER_APPROVAL_LIMIT = "OVER_APPROVAL_LIMIT"
    # --- Notes: shown on the decision, never change the outcome ---
    UNPLANNED_CHARGE_ALLOWED = "UNPLANNED_CHARGE_ALLOWED"
    PRICES_INCLUDE_TAX = "PRICES_INCLUDE_TAX"
