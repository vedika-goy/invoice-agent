"""Runs the whole process for one file: intake, the 7 steps, saving the decision and recording approvals once."""
import logging
import sqlite3
from collections.abc import Callable
from datetime import date, timedelta

from invoice_engine.decision.service import (
    DECIDE_STEP_NUMBER,
    DECIDE_STEP_TITLE,
    EXPLAIN_STEP_NUMBER,
    EXPLAIN_STEP_TITLE,
    build_decide_step,
    build_explain_step,
    build_policy_findings,
    decide,
)
from invoice_engine.decision.types import OUTCOME_LABELS, Outcome
from invoice_engine.duplicate_check.service import (
    DUPLICATE_STEP_NUMBER,
    DUPLICATE_STEP_TITLE,
    KnownInvoice,
    check_duplicates,
    normalize_invoice_number,
)
from invoice_engine.intake.schemas import IntakeResult
from invoice_engine.intake.service import INTAKE_STEP_NUMBER, INTAKE_STEP_TITLE, build_intake_step, check_uploaded_file
from invoice_engine.ledger.repository import LedgerRepository
from invoice_engine.ledger.schemas import LedgerInvoice, LedgerLine, LedgerSource
from invoice_engine.numbers_check.schemas import InvoiceFacts
from invoice_engine.numbers_check.service import (
    BILL_DOCUMENT_TYPES,
    NUMBERS_STEP_NUMBER,
    NUMBERS_STEP_TITLE,
    build_invoice_facts,
    check_reading_and_numbers,
)
from invoice_engine.pipeline.schemas import (
    DecisionRecord,
    DecisionTrigger,
    InvoiceSummary,
    PipelineRunResult,
    StepResult,
)
from invoice_engine.po_match.service import PO_STEP_NUMBER, PO_STEP_TITLE, match_purchase_order
from invoice_engine.reading.schemas import DocumentType, InvoiceReading
from invoice_engine.reading.service import READ_STEP_NUMBER, READ_STEP_TITLE, InvoiceReadingService, build_read_step
from invoice_engine.reference_data.repository import ReferenceDataRepository
from invoice_engine.reference_data.schemas import Vendor
from invoice_engine.run_history.repository import RunHistoryRepository
from invoice_engine.run_history.schemas import ReviewerAction, ReviewerActionType
from invoice_engine.utils.pdf_document import extract_pdf_text
from invoice_engine.vendor_match.service import VENDOR_STEP_NUMBER, VENDOR_STEP_TITLE, check_vendor, find_vendor

logger = logging.getLogger(__name__)

RECORD_APPROVAL_STEP_NUMBER = 8
RECORD_APPROVAL_STEP_TITLE = "Record the approval"
StepCallback = Callable[[StepResult], None]


class InvoicePipelineService:
    def __init__(self, connection: sqlite3.Connection, reading_service: InvoiceReadingService,
                 today_provider: Callable[[], date] = date.today) -> None:
        # --- Injected dependencies ---
        self._reading_service = reading_service
        self._today_provider = today_provider
        # --- Repositories on the run database ---
        self._run_history = RunHistoryRepository(connection)
        self._ledger = LedgerRepository(connection)
        self._reference_data = ReferenceDataRepository(connection)

    def process_upload(self, pdf_bytes: bytes, file_name: str,
                       on_step_completed: StepCallback | None = None) -> PipelineRunResult:
        """A file seen before opens its earlier run instead of getting a second decision."""
        intake = check_uploaded_file(pdf_bytes)
        if not intake.is_valid:
            _report_step([], build_intake_step(intake, file_name, None), on_step_completed)
            return PipelineRunResult(run_id=None, decision_id=None, was_already_seen=False,
                                     intake_problem=intake.problem, record=None)
        run_id, was_created = self._run_history.create_run(intake.fingerprint, file_name, pdf_bytes)
        if not was_created:
            _report_step([], build_intake_step(intake, file_name, run_id), on_step_completed)
            latest = self._run_history.get_latest_decision(run_id)
            return PipelineRunResult(run_id=run_id, decision_id=latest.decision_id if latest else None,
                                     was_already_seen=True, intake_problem=None, record=latest.record if latest else None)
        return self._evaluate_run(run_id, pdf_bytes, file_name, intake, DecisionTrigger.UPLOAD, None, on_step_completed)

    def rerun(self, run_id: int, on_step_completed: StepCallback | None = None) -> PipelineRunResult:
        """Runs every check again on the current data, with the saved reading and any PO the reviewer chose."""
        latest = self._run_history.get_latest_decision(run_id)
        po_number_override = latest.record.po_number_override if latest else None
        return self._reevaluate_run(run_id, DecisionTrigger.RERUN, po_number_override, on_step_completed)

    def use_po(self, run_id: int, po_number: str, on_step_completed: StepCallback | None = None) -> PipelineRunResult:
        """Re-decides the run against a PO the reviewer picked, e.g. the suggested one."""
        return self._reevaluate_run(run_id, DecisionTrigger.USE_SUGGESTED_PO, po_number, on_step_completed)

    def record_reviewer_action(self, run_id: int, action: ReviewerActionType, reviewer_note: str) -> ReviewerAction:
        """Keeps both the system's recommendation and the person's decision. An approval is recorded once."""
        if not reviewer_note.strip():
            raise ValueError("A reviewer must give a reason.")
        latest = self._run_history.get_latest_decision(run_id)
        if latest is None:
            raise LookupError(f"Run {run_id} has no decision to act on.")
        if action == ReviewerActionType.APPROVE:
            self._record_approval_once(run_id, latest.record.invoice_summary, latest.record.billable_lines)
        return self._run_history.add_reviewer_action(run_id, latest.decision_id, action,
                                                     latest.record.decision.outcome, reviewer_note.strip())

    def _reevaluate_run(self, run_id: int, trigger: DecisionTrigger, po_number_override: str | None,
                        on_step_completed: StepCallback | None) -> PipelineRunResult:
        run = self._run_history.get_run(run_id)
        if run is None:
            raise LookupError(f"Run {run_id} doesn't exist.")
        intake = check_uploaded_file(run.pdf_bytes)
        return self._evaluate_run(run_id, run.pdf_bytes, run.file_name, intake, trigger, po_number_override,
                                  on_step_completed)

    def _evaluate_run(self, run_id: int, pdf_bytes: bytes, file_name: str, intake: IntakeResult,
                      trigger: DecisionTrigger, po_number_override: str | None,
                      on_step_completed: StepCallback | None) -> PipelineRunResult:
        steps: list[StepResult] = []
        _report_step(steps, build_intake_step(intake, file_name, None), on_step_completed)
        reading_result = self._reading_service.read(pdf_bytes, intake.fingerprint, is_scan=not intake.has_text_layer)
        _report_step(steps, build_read_step(reading_result), on_step_completed)
        invoice_summary, vendor, billable_lines = self._run_checks(
            run_id, pdf_bytes, intake, reading_result.reading, po_number_override, steps, on_step_completed)
        policy_findings = build_policy_findings(invoice_summary)
        all_findings = [finding for step in steps for finding in step.findings] + policy_findings
        decision = decide(all_findings, invoice_summary, vendor)
        _report_step(steps, build_decide_step(decision, policy_findings), on_step_completed)
        _report_step(steps, build_explain_step(decision), on_step_completed)
        if decision.outcome == Outcome.APPROVED:
            _report_step(steps, self._build_record_approval_step(run_id, invoice_summary, billable_lines),
                         on_step_completed)
        record = DecisionRecord(trigger=trigger, po_number_override=po_number_override, invoice_summary=invoice_summary,
                                steps=steps, decision=decision, reading_report=reading_result.report,
                                billable_lines=billable_lines)
        decision_id = self._run_history.add_decision(run_id, record)
        return PipelineRunResult(run_id=run_id, decision_id=decision_id, was_already_seen=False,
                                 intake_problem=None, record=record)

    def _run_checks(self, run_id: int, pdf_bytes: bytes, intake: IntakeResult, reading: InvoiceReading | None,
                    po_number_override: str | None, steps: list[StepResult],
                    on_step_completed: StepCallback | None) -> tuple[InvoiceSummary, Vendor | None, list[LedgerLine]]:
        """Steps 2 to 5. Mutates: steps."""
        if reading is None:
            for step_number, title in _CHECK_STEPS_AFTER_READING:
                _report_step(steps, StepResult.skipped(step_number, title, "Skipped: the invoice couldn't be read."),
                             on_step_completed)
            return _build_invoice_summary(None, None, None), None, []
        facts = build_invoice_facts(reading)
        pdf_text = extract_pdf_text(pdf_bytes) if intake.has_text_layer else None
        _report_step(steps, check_reading_and_numbers(reading, facts, pdf_text, self._today_provider()), on_step_completed)
        if facts.document_type not in BILL_DOCUMENT_TYPES:
            for step_number, title in _CHECK_STEPS_AFTER_READING[1:]:
                _report_step(steps, StepResult.skipped(step_number, title, "Skipped: not an invoice."), on_step_completed)
            return _build_invoice_summary(facts, None, None), None, []
        vendors = self._reference_data.list_vendors()
        vendor_match = find_vendor(facts, vendors)
        vendor = vendor_match.vendor
        _report_step(steps, check_vendor(facts, vendor_match), on_step_completed)
        _report_step(steps, check_duplicates(facts, vendor, self._list_known_invoices(run_id)), on_step_completed)
        po_result = match_purchase_order(
            facts, vendor, self._reference_data.list_purchase_order_lines(),
            {known_vendor.vendor_id: known_vendor for known_vendor in vendors},
            self._ledger.build_billed_to_date(excluded_run_id=run_id), po_number_override)
        _report_step(steps, po_result.step, on_step_completed)
        return _build_invoice_summary(facts, vendor, po_result.po_number), vendor, po_result.billable_lines

    def _list_known_invoices(self, run_id: int) -> list[KnownInvoice]:
        """Paid and approved invoices, plus invoices open in other runs, never the run being evaluated."""
        ledger_invoices = [invoice for invoice in self._ledger.list_invoices() if invoice.run_id != run_id]
        known_invoices = [
            KnownInvoice(vendor_id=invoice.vendor_id, invoice_number=invoice.invoice_number,
                         invoice_date=invoice.invoice_date, total=invoice.invoice_total, status_label=invoice.status_label)
            for invoice in ledger_invoices
        ]
        recorded_run_ids = {invoice.run_id for invoice in ledger_invoices if invoice.run_id is not None}
        for stored in self._run_history.list_latest_decisions():
            summary, outcome = stored.record.invoice_summary, stored.record.decision.outcome
            if stored.run_id == run_id or stored.run_id in recorded_run_ids or outcome == Outcome.REJECTED:
                continue
            if summary.document_type != DocumentType.INVOICE or None in (
                    summary.vendor_id, summary.invoice_number, summary.invoice_date, summary.total):
                continue
            known_invoices.append(KnownInvoice(
                vendor_id=summary.vendor_id, invoice_number=summary.invoice_number, invoice_date=summary.invoice_date,
                total=summary.total, status_label=f"open in run {stored.run_id} ({OUTCOME_LABELS[outcome].lower()})"))
        return known_invoices

    def _build_record_approval_step(self, run_id: int, invoice_summary: InvoiceSummary,
                                    billable_lines: list[LedgerLine]) -> StepResult:
        was_recorded = self._record_approval_once(run_id, invoice_summary, billable_lines)
        if was_recorded:
            detail = "Recorded in the ledger: it now counts toward billed-to-date and duplicate checks."
        else:
            detail = "Already in the ledger, so nothing changed: an invoice is only ever counted once."
        return StepResult.from_findings(RECORD_APPROVAL_STEP_NUMBER, RECORD_APPROVAL_STEP_TITLE, [detail], [])

    def _record_approval_once(self, run_id: int, summary: InvoiceSummary, billable_lines: list[LedgerLine]) -> bool:
        if summary.document_type != DocumentType.INVOICE or summary.vendor_id is None or summary.total is None:
            logger.info("Run %d approved without a ledger entry (no matched vendor, total or not an invoice).", run_id)
            return False
        invoice_number = summary.invoice_number or f"RUN-{run_id}"
        ledger_invoice = LedgerInvoice(
            vendor_id=summary.vendor_id,
            invoice_number=invoice_number,
            # A missing number gets a run-scoped key, so it can't collide with a real invoice number.
            invoice_number_normalized=summary.invoice_number_normalized or f"run-{run_id}",
            invoice_date=summary.invoice_date or self._today_provider(),
            invoice_total=summary.total,
            currency=summary.currency_code or "USD",
            source=LedgerSource.RUN,
            run_id=run_id,
            status_label=f"approved in run {run_id}",
            lines=billable_lines,
        )
        return self._ledger.record_invoice_once(ledger_invoice)


_CHECK_STEPS_AFTER_READING = [
    (NUMBERS_STEP_NUMBER, NUMBERS_STEP_TITLE),
    (VENDOR_STEP_NUMBER, VENDOR_STEP_TITLE),
    (DUPLICATE_STEP_NUMBER, DUPLICATE_STEP_TITLE),
    (PO_STEP_NUMBER, PO_STEP_TITLE),
]


# Every step in run order, for showing the whole process before it runs. The last one runs only on approval.
PIPELINE_STEPS: list[tuple[int, str]] = [
    (INTAKE_STEP_NUMBER, INTAKE_STEP_TITLE),
    (READ_STEP_NUMBER, READ_STEP_TITLE),
    *_CHECK_STEPS_AFTER_READING,
    (DECIDE_STEP_NUMBER, DECIDE_STEP_TITLE),
    (EXPLAIN_STEP_NUMBER, EXPLAIN_STEP_TITLE),
    (RECORD_APPROVAL_STEP_NUMBER, RECORD_APPROVAL_STEP_TITLE),
]


def _report_step(steps: list[StepResult], step: StepResult, on_step_completed: StepCallback | None) -> None:
    """Mutates: steps. Calls on_step_completed so the live view can show the step as soon as it is done."""
    steps.append(step)
    if on_step_completed is not None:
        on_step_completed(step)


def _build_invoice_summary(facts: InvoiceFacts | None, vendor: Vendor | None, po_number: str | None) -> InvoiceSummary:
    if facts is None:
        return InvoiceSummary(document_type=None, vendor_id=None, vendor_name=None, invoice_number=None,
                              invoice_number_normalized=None, invoice_date=None, due_date=None, total=None,
                              currency_code=None, po_number=None)
    due_date = facts.due_date
    if due_date is None and facts.invoice_date is not None and vendor is not None:
        due_date = facts.invoice_date + timedelta(days=vendor.payment_terms_days)
    return InvoiceSummary(
        document_type=facts.document_type.value,
        vendor_id=vendor.vendor_id if vendor else None,
        vendor_name=vendor.vendor_name if vendor else facts.vendor_name,
        invoice_number=facts.invoice_number,
        invoice_number_normalized=normalize_invoice_number(facts.invoice_number) if facts.invoice_number else None,
        invoice_date=facts.invoice_date,
        due_date=due_date,
        total=facts.total,
        currency_code=facts.currency_code,
        po_number=po_number or facts.po_number,
    )
