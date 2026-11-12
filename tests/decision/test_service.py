from datetime import date
from decimal import Decimal

from invoice_engine.decision.service import build_finding, build_policy_findings, decide
from invoice_engine.decision.types import Outcome, ReasonCode
from invoice_engine.pipeline.schemas import InvoiceSummary
from tests.factories import load_test_vendor


def _summary(total: str = "420.00", document_type: str = "invoice") -> InvoiceSummary:
    return InvoiceSummary(document_type=document_type, vendor_id="V002", vendor_name="Summit Packaging LLC",
                          invoice_number=None, invoice_number_normalized=None, invoice_date=date(2026, 11, 6),
                          due_date=date(2026, 12, 6), total=Decimal(total), currency_code="USD", po_number="PO-2051")


def test_no_findings_means_approved():
    assert decide([], _summary(), None).outcome == Outcome.APPROVED


def test_notes_never_change_an_approval():
    note = build_finding(ReasonCode.UNPLANNED_CHARGE_ALLOWED, charges="Shipping", amount="$40.00", allowance="$75.00")
    assert decide([note], _summary(), None).outcome == Outcome.APPROVED


def test_most_serious_outcome_wins_and_every_reason_is_kept():
    findings = [
        build_finding(ReasonCode.CREDIT_NOTE, total="$1.00", vendor_name="X"),
        build_finding(ReasonCode.BANK_ACCOUNT_CHANGED, invoice_last4="1", file_last4="2", vendor_name="X", phone_on_file="0"),
        build_finding(ReasonCode.NOT_AN_INVOICE, document_type_label="statement of account"),
    ]
    decision = decide(findings, _summary(), None)
    assert decision.outcome == Outcome.REJECTED
    assert [finding.code for finding in decision.findings] == [
        ReasonCode.NOT_AN_INVOICE, ReasonCode.BANK_ACCOUNT_CHANGED, ReasonCode.CREDIT_NOTE]
    assert decision.owners == ["AP clerk", "Treasury"]


def test_only_invoices_over_25000_need_a_second_approver():
    assert [f.code for f in build_policy_findings(_summary(total="25000.01"))] == [ReasonCode.OVER_APPROVAL_LIMIT]
    assert build_policy_findings(_summary(total="25000.00")) == []
    assert build_policy_findings(_summary(total="30000.00", document_type="credit_note")) == []


def test_missing_information_drafts_an_email_to_the_vendor():
    finding = build_finding(ReasonCode.MISSING_REQUIRED_FIELD, missing_fields="invoice number")
    draft = decide([finding], _summary(), load_test_vendor("V002")).vendor_email_draft
    assert draft.startswith("To: ar@summitpackaging.example")
    assert "doesn't show the invoice number" in draft
