"""Steps 6 and 7: turn the findings of every check into one outcome, owners and plain-English reasons."""
from invoice_engine.decision.config import BUYER_COMPANY_NAME, REASON_RULES, VENDOR_EMAIL_TEMPLATE
from invoice_engine.decision.schemas import Decision, Finding
from invoice_engine.decision.types import OUTCOME_LABELS, OUTCOME_SEVERITY_RANK, Outcome, ReasonCode
from invoice_engine.pipeline.schemas import InvoiceSummary, StepResult
from invoice_engine.policy.config import APPROVAL_LIMIT_USD, POLICY_VERSION
from invoice_engine.reading.schemas import DocumentType
from invoice_engine.reference_data.schemas import Vendor
from invoice_engine.utils.money import format_money

DECIDE_STEP_NUMBER = 6
DECIDE_STEP_TITLE = "Decide"
EXPLAIN_STEP_NUMBER = 7
EXPLAIN_STEP_TITLE = "Explain"


def build_finding(
    code: ReasonCode,
    *,
    measured: str | None = None,
    limit: str | None = None,
    owner_name: str | None = None,
    **details: str,
) -> Finding:
    rule = REASON_RULES[code]
    return Finding(
        code=code,
        outcome=rule.outcome,
        owner=rule.owner,
        owner_name=owner_name,
        title=rule.title,
        explanation=rule.explanation_template.format(**details),
        unblock_action=rule.unblock_template.format(**details) if rule.unblock_template else None,
        measured=measured,
        limit=limit,
        details=details,
    )


def build_policy_findings(invoice_summary: InvoiceSummary) -> list[Finding]:
    """Rules about the invoice as a whole rather than its contents: currently the approval limit."""
    total = invoice_summary.total
    if invoice_summary.document_type != DocumentType.INVOICE or total is None or total <= APPROVAL_LIMIT_USD:
        return []
    return [
        build_finding(
            ReasonCode.OVER_APPROVAL_LIMIT,
            measured=format_money(total, invoice_summary.currency_code),
            limit=format_money(APPROVAL_LIMIT_USD),
            total=format_money(total, invoice_summary.currency_code),
            limit_amount=format_money(APPROVAL_LIMIT_USD),
        )
    ]


def decide(findings: list[Finding], invoice_summary: InvoiceSummary, vendor: Vendor | None) -> Decision:
    """The most serious outcome among the findings wins; every finding is kept as a reason."""
    ordered_findings = sorted(findings, key=_build_finding_sort_key)
    blocking_findings = [finding for finding in ordered_findings if finding.outcome is not None]
    outcome = blocking_findings[0].outcome if blocking_findings else Outcome.APPROVED
    owners: list[str] = []
    for finding in blocking_findings:
        owner_label = finding.owner_name or (finding.owner.value if finding.owner else None)
        if owner_label and owner_label not in owners:
            owners.append(owner_label)
    suggested_po_numbers = [f.details["po_number"] for f in findings if f.code == ReasonCode.NO_PO_LIKELY_PO_FOUND]
    return Decision(
        outcome=outcome,
        findings=ordered_findings,
        owners=owners,
        policy_version=POLICY_VERSION,
        total=invoice_summary.total,
        currency_code=invoice_summary.currency_code,
        due_date=invoice_summary.due_date,
        suggested_po_number=suggested_po_numbers[0] if suggested_po_numbers else None,
        vendor_email_draft=_build_vendor_email_draft(findings, invoice_summary, vendor),
    )


def build_decide_step(decision: Decision, policy_findings: list[Finding]) -> StepResult:
    """policy_findings are the ones this step itself raised (build_policy_findings), shown on this step."""
    blocking_count = sum(1 for finding in decision.findings if finding.outcome is not None)
    details = [f"Outcome: {OUTCOME_LABELS[decision.outcome]}, from {blocking_count} blocking reason(s)."]
    if decision.owners:
        details.append(f"Who handles it: {', '.join(decision.owners)}.")
    details.append(f"Policy version {decision.policy_version}.")
    return StepResult.from_findings(DECIDE_STEP_NUMBER, DECIDE_STEP_TITLE, details, policy_findings)


def build_explain_step(decision: Decision) -> StepResult:
    details = [finding.explanation for finding in decision.findings]
    if not details:
        details = ["Every check passed, so the invoice is ready to pay."]
    if decision.vendor_email_draft:
        details.append("Drafted an email asking the vendor for the missing information.")
    return StepResult.from_findings(EXPLAIN_STEP_NUMBER, EXPLAIN_STEP_TITLE, details, [])


def _build_finding_sort_key(finding: Finding) -> int:
    if finding.outcome is None:
        return 1  # notes go last
    return -OUTCOME_SEVERITY_RANK[finding.outcome]


def _build_vendor_email_draft(
    findings: list[Finding], invoice_summary: InvoiceSummary, vendor: Vendor | None
) -> str | None:
    missing_field_findings = [f for f in findings if f.code == ReasonCode.MISSING_REQUIRED_FIELD]
    if not missing_field_findings:
        return None
    invoice_reference = (
        f"dated {invoice_summary.invoice_date.isoformat()}" if invoice_summary.invoice_date else "(no date)"
    )
    total = invoice_summary.total
    return VENDOR_EMAIL_TEMPLATE.format(
        remit_email=vendor.remit_email if vendor else "[vendor's email]",
        vendor_name=vendor.vendor_name if vendor else (invoice_summary.vendor_name or "[vendor]"),
        invoice_reference=invoice_reference,
        total=format_money(total, invoice_summary.currency_code) if total is not None else "an unknown amount",
        missing_fields=missing_field_findings[0].details["missing_fields"],
        buyer_company_name=BUYER_COMPANY_NAME,
    )
