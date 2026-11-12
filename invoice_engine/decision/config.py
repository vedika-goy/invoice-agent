"""The rules table: for each reason code, its outcome, owner, plain-English templates and why it exists.

Templates are filled with str.format from the details a check passes to build_finding().
"""
from dataclasses import dataclass

from invoice_engine.decision.types import Outcome, Owner, ReasonCode

BUYER_COMPANY_NAME = "Brightwater Markets Inc."


@dataclass(frozen=True)
class ReasonRule:
    outcome: Outcome | None  # None marks a note, which never changes the outcome
    owner: Owner | None
    title: str
    explanation_template: str
    unblock_template: str | None
    why: str


REASON_RULES: dict[ReasonCode, ReasonRule] = {
    ReasonCode.NOT_AN_INVOICE: ReasonRule(
        Outcome.REJECTED, Owner.AP_CLERK, "Not an invoice",
        "This document is a {document_type_label}, not a bill, so there is nothing to pay.",
        "Ask the vendor for the invoice itself if a payment is due.",
        "Statements, quotes and POs arrive in the same inbox, but they aren't bills.",
    ),
    ReasonCode.DUPLICATE_CONFIRMED: ReasonRule(
        Outcome.REJECTED, Owner.AP_CLERK, "Confirmed duplicate",
        "Invoice {invoice_number} is the same invoice as {original_invoice_number} dated {original_invoice_date}, "
        "which is already {original_status}. Paying it would pay twice.",
        "Nothing to pay. Reply to the vendor with the payment details of {original_invoice_number}.",
        "Paying twice is the most common expensive AP mistake.",
    ),
    ReasonCode.VENDOR_BLOCKED: ReasonRule(
        Outcome.REJECTED, Owner.VENDOR_MASTER_TEAM, "Vendor is blocked",
        "{vendor_name} is blocked in the vendor master, so it must not be paid.",
        "Vendor master team checks why the vendor is blocked.",
        "A blocked vendor must not be paid, whatever the invoice says.",
    ),
    ReasonCode.BANK_ACCOUNT_CHANGED: ReasonRule(
        Outcome.ON_HOLD, Owner.TREASURY, "Bank account differs from the one on file",
        "The invoice asks for payment to an account ending {invoice_last4}, "
        "but the account on file for {vendor_name} ends {file_last4}.",
        "Treasury calls {vendor_name} on {phone_on_file}, the number on file, to confirm the change "
        "before anything is paid.",
        "Fake bank-change notices are a common fraud. Only a call to the known number settles it.",
    ),
    ReasonCode.MISSING_REQUIRED_FIELD: ReasonRule(
        Outcome.ON_HOLD, Owner.AP_CLERK, "Missing invoice number, date or total",
        "The invoice has no {missing_fields}, so it can't be recorded or checked for duplicates.",
        "Send the drafted email asking the vendor for a corrected invoice.",
        "An invoice can't be recorded or checked for duplicates without these.",
    ),
    ReasonCode.QUANTITY_NOT_RECEIVED: ReasonRule(
        Outcome.ON_HOLD, Owner.RECEIVING, "Billed quantity is more than was received",
        "{po_number} line {po_line}: {ordered} ordered, {received} received and {billed_before} already billed, "
        "so {not_received} billed here haven't arrived yet.",
        "Receiving logs receipt of {not_received} on {po_number} line {po_line}, then re-run.",
        "Pay only for goods that arrived. This clears once the delivery is logged.",
    ),
    ReasonCode.READING_FAILED: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.AP_CLERK, "Couldn't read the invoice",
        "The invoice couldn't be read: {problem}.",
        "Read the PDF and enter the invoice by hand, or re-run when the AI service is back.",
        "Never act on a number the process isn't sure it read correctly.",
    ),
    ReasonCode.QUOTE_NOT_IN_DOCUMENT: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.AP_CLERK, "A value read isn't in the PDF",
        "These values aren't printed in the PDF the way they were read, so they may be misread: {field_list}.",
        "Check those values against the PDF and correct or confirm them.",
        "Never act on a number the process isn't sure it read correctly.",
    ),
    ReasonCode.SCAN_READINGS_DISAGREE: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.AP_CLERK, "Two readings of the scan disagree",
        "The scan was read twice and the two readings disagree on {field_list}.",
        "Check those values against the scan and correct or confirm them.",
        "Never act on a number the process isn't sure it read correctly.",
    ),
    ReasonCode.MULTIPLE_INVOICES_IN_FILE: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.AP_CLERK, "More than one invoice in the file",
        "The file contains {invoice_count} invoices, and each has to be checked on its own.",
        "Split the file and upload each invoice separately.",
        "Each invoice has to be checked on its own.",
    ),
    ReasonCode.CREDIT_NOTE: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.AP_CLERK, "Credit note",
        "This is a credit note for {total}. It reduces what is owed instead of being paid out.",
        "Apply the credit against {vendor_name}'s next payment.",
        "A credit is set against future payments, not paid out.",
    ),
    ReasonCode.POSSIBLE_DUPLICATE: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.AP_CLERK, "Possible duplicate",
        "Same vendor and amount ({total}) as {other_invoice_number} dated {other_invoice_date}, "
        "{days_apart} days apart, which is {other_status}, but the invoice number is different.",
        "Compare the two invoices side by side. Approve only if it is a genuine repeat order.",
        "It could be a resend or a genuine repeat order, and a person can tell which.",
    ),
    ReasonCode.VENDOR_NOT_FOUND: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.VENDOR_MASTER_TEAM, "Vendor not recognised",
        "'{vendor_name}' isn't in the vendor master, and no tax ID matched.",
        "Vendor master team confirms who the vendor is, or sets them up as a new vendor.",
        "An unknown payee must be set up and checked before it is paid.",
    ),
    ReasonCode.VENDOR_SIMILAR_NAME_ONLY: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.VENDOR_MASTER_TEAM, "Vendor matched by a similar name only",
        "'{vendor_name}' only resembles '{matched_vendor_name}' ({similarity} similar), and the tax ID didn't match.",
        "Vendor master team confirms whether this is {matched_vendor_name}.",
        "A lookalike name could be a typo or an impersonator, so someone has to confirm who it is.",
    ),
    ReasonCode.NO_PO_LIKELY_PO_FOUND: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.AP_CLERK, "No PO on the invoice (likely PO suggested)",
        "The invoice names no PO. Likely {po_number}: same vendor, all {line_count} items match, "
        "{invoice_amount} before tax vs {po_amount} left on the PO ({difference_percent} apart).",
        "Check {po_number} and click Use this PO.",
        "The suggestion saves the reviewer time, but a guess shouldn't release money.",
    ),
    ReasonCode.NO_PO_SEVERAL_POS_FIT: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.AP_CLERK, "No PO on the invoice (several POs fit)",
        "The invoice names no PO, and {po_numbers} fit it equally well, so none is suggested.",
        "Ask the requester which PO this delivery belongs to, then use that PO.",
        "When two POs fit equally well, picking one is a guess, so the process suggests neither.",
    ),
    ReasonCode.NO_PO_NO_PO_FITS: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.AP_CLERK, "No PO on the invoice (none fits)",
        "The invoice names no PO, and none of {vendor_name}'s open POs fits its items, prices and quantities.",
        "Ask the vendor or the requester for the PO number.",
        "Spending without a PO needs someone to confirm it was ordered.",
    ),
    ReasonCode.PO_NOT_FOUND: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.PROCUREMENT, "PO not found",
        "The invoice names {po_number}, which doesn't exist.",
        "Procurement finds the right PO or confirms the purchase.",
        "Spending without a valid PO needs the buyer's sign-off.",
    ),
    ReasonCode.PO_OTHER_VENDOR: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.PROCUREMENT, "PO belongs to another vendor",
        "{po_number} was raised for {po_vendor_name}, not {vendor_name}.",
        "Procurement confirms which PO this invoice belongs to.",
        "Spending without a valid PO needs the buyer's sign-off.",
    ),
    ReasonCode.PO_CLOSED: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.PROCUREMENT, "PO is closed",
        "{po_number} is closed, so nothing more should be billed against it.",
        "Procurement reopens the PO or raises a new one.",
        "Spending without a valid PO needs the buyer's sign-off.",
    ),
    ReasonCode.CURRENCY_MISMATCH: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.AP_CLERK, "Currency differs from the PO",
        "The invoice is in {invoice_currency}, but {po_number} is in {po_currency}.",
        "Ask the vendor to re-bill in {po_currency}, or confirm the exchange rate with the buyer.",
        "Paying in the wrong currency changes the amount paid.",
    ),
    ReasonCode.PRICE_ABOVE_PO: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.PO_REQUESTER, "Price more than 2% above the PO",
        "{item} is billed at {invoice_price} per {unit}, {difference_percent} above the PO price of "
        "{po_price} (limit {limit_percent}).",
        "{requester} approves the new price, or the vendor re-bills at {po_price}.",
        "Small rounding differences are fine; a real price rise needs the buyer's OK.",
    ),
    ReasonCode.UNPLANNED_CHARGE_OVER_ALLOWANCE: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.PO_REQUESTER, "Charge not on the PO, over the allowance",
        "{charges} aren't on the PO and add up to {amount}, over the {allowance} allowance.",
        "{requester} approves the extra charges, or the vendor removes them.",
        "Small freight or fuel charges are normal; larger ones need the buyer's OK.",
    ),
    ReasonCode.PO_OVERBILLED: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.PROCUREMENT, "Total billed would exceed the PO",
        "{po_number} line {po_line} ordered {ordered}. {billed_before} already billed plus {billed_now} "
        "on this invoice makes {billed_total}, which is {over} more than ordered.",
        "Procurement raises the PO quantity, or the vendor credits the extra {over}.",
        "Catches split invoices that together add up to more than was ordered.",
    ),
    ReasonCode.NUMBERS_DONT_ADD_UP: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.AP_CLERK, "Numbers don't add up",
        "{calculation}, but the invoice says {printed}.",
        "Check the invoice. If it is wrong, ask the vendor for a corrected one.",
        "Either the invoice is wrong or it was misread, and both need a look.",
    ),
    ReasonCode.INVOICE_DATE_IN_FUTURE: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.AP_CLERK, "Invoice date is in the future",
        "The invoice is dated {invoice_date}, which is after today ({today}).",
        "Check the date against the PDF, or ask the vendor for a corrected invoice.",
        "A future date means a typo or a misread, and it shifts the due date.",
    ),
    ReasonCode.DUE_DATE_BEFORE_INVOICE_DATE: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.AP_CLERK, "Due date is before the invoice date",
        "The due date {due_date} is before the invoice date {invoice_date}.",
        "Check both dates against the PDF, or ask the vendor for a corrected invoice.",
        "Impossible dates mean a typo or a misread.",
    ),
    ReasonCode.OVER_APPROVAL_LIMIT: ReasonRule(
        Outcome.NEEDS_REVIEW, Owner.AP_MANAGER, "Over the approval limit",
        "The total of {total} is over the {limit_amount} approval limit, so it needs a second approver.",
        "AP manager gives the second approval.",
        "Large payments get a second approver.",
    ),
    ReasonCode.UNPLANNED_CHARGE_ALLOWED: ReasonRule(
        None, None, "Small charge not on the PO",
        "{charges} of {amount} isn't on the PO, which is within the {allowance} allowance.",
        None,
        "Small freight or fuel charges are normal and not worth a review.",
    ),
    ReasonCode.PRICES_INCLUDE_TAX: ReasonRule(
        None, None, "Prices include tax",
        "Prices include tax ({tax} in total), so they were converted to before-tax amounts before "
        "comparing with the PO.",
        None,
        "PO prices are before tax, so tax-inclusive prices would otherwise look like a price rise.",
    ),
}

VENDOR_EMAIL_TEMPLATE = """To: {remit_email}
Subject: Corrected invoice needed: {vendor_name}, {invoice_reference}

Hello {vendor_name} team,

We received your invoice {invoice_reference} for {total}, but it doesn't show the {missing_fields}. \
We can't record or pay it without this.

Please send a corrected invoice in reply to this email.

Thank you,
Accounts Payable, {buyer_company_name}"""
