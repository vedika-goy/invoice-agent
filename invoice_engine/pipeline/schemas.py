from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from invoice_engine.decision.schemas import Decision, Finding
from invoice_engine.decision.types import Outcome
from invoice_engine.ledger.schemas import LedgerLine
from invoice_engine.reading.schemas import ReadingReport


class StepStatus(StrEnum):
    PASSED = "passed"
    WARNING = "warning"  # a finding sends the invoice to review or on hold
    FAILED = "failed"  # a finding rejects the invoice
    SKIPPED = "skipped"


class StepResult(BaseModel):
    """One step of the live run view: what it checked, what it concluded, and its findings."""

    step_number: int
    title: str
    status: StepStatus
    details: list[str]
    findings: list[Finding]

    @classmethod
    def from_findings(cls, step_number: int, title: str, details: list[str], findings: list[Finding]) -> "StepResult":
        outcomes = {finding.outcome for finding in findings if finding.outcome is not None}
        if Outcome.REJECTED in outcomes:
            status = StepStatus.FAILED
        elif outcomes:
            status = StepStatus.WARNING
        else:
            status = StepStatus.PASSED
        return cls(step_number=step_number, title=title, status=status, details=details, findings=findings)

    @classmethod
    def skipped(cls, step_number: int, title: str, reason: str) -> "StepResult":
        return cls(step_number=step_number, title=title, status=StepStatus.SKIPPED, details=[reason], findings=[])


class DecisionTrigger(StrEnum):
    UPLOAD = "upload"
    RERUN = "rerun"
    USE_SUGGESTED_PO = "use_suggested_po"


class InvoiceSummary(BaseModel):
    """The invoice's key facts, kept with each decision for the dashboard and for duplicate checks."""

    document_type: str | None
    vendor_id: str | None
    vendor_name: str | None
    invoice_number: str | None
    invoice_number_normalized: str | None
    invoice_date: date | None
    due_date: date | None
    total: Decimal | None
    currency_code: str | None
    po_number: str | None  # the PO used: chosen by the reviewer, else the one printed


class DecisionRecord(BaseModel):
    """Everything one evaluation of a run produced; stored as one row per decision."""

    trigger: DecisionTrigger
    po_number_override: str | None
    invoice_summary: InvoiceSummary
    steps: list[StepResult]
    decision: Decision
    reading_report: ReadingReport | None
    billable_lines: list[LedgerLine]  # what an approval adds to billed-to-date


class PipelineRunResult(BaseModel):
    run_id: int | None  # None when the file was refused at intake
    decision_id: int | None
    was_already_seen: bool
    intake_problem: str | None
    record: DecisionRecord | None
