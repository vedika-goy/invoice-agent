"""Plays samples/expected.csv, in order, on a throwaway database and compares each outcome with the expected one.

The order matters: EC-1 depends on earlier invoices being approved, and the script logs a delivery between runs.
"""
import csv
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from invoice_engine.config import EXPECTED_RESULTS_PATH, SAMPLE_INVOICES_FOLDER
from invoice_engine.database.connection import IN_MEMORY_DATABASE, open_database_connection
from invoice_engine.decision.types import Outcome, ReasonCode
from invoice_engine.demo_data.service import reset_demo_data
from invoice_engine.pipeline.schemas import PipelineRunResult
from invoice_engine.pipeline.service import InvoicePipelineService
from invoice_engine.reading.service import InvoiceReadingService
from invoice_engine.reference_data.repository import ReferenceDataRepository
from invoice_engine.run_history.repository import RunHistoryRepository


class SelfTestAction(StrEnum):
    PROCESS = "process"  # target: sample file name
    LOG_RECEIPT = "log_receipt"  # target: "PO-2041:1:400" (PO, line, quantity received now)
    RERUN = "rerun"  # target: sample file name processed earlier
    USE_SUGGESTED_PO = "use_suggested_po"  # target: sample file name processed earlier


class SelfTestStep(BaseModel):
    step_number: int
    action: SelfTestAction
    target: str
    expected_outcome: Outcome | None  # None for steps that only change data
    expected_reason_codes: list[ReasonCode]
    why: str


class SelfTestStepResult(BaseModel):
    step: SelfTestStep
    actual_outcome: Outcome | None
    actual_reason_codes: list[ReasonCode]
    is_match: bool
    problem: str | None


def load_self_test_steps(csv_path: Path = EXPECTED_RESULTS_PATH) -> list[SelfTestStep]:
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    return [
        SelfTestStep(
            step_number=int(row["step"]),
            action=SelfTestAction(row["action"]),
            target=row["target"],
            expected_outcome=Outcome(row["expected_outcome"]) if row["expected_outcome"] else None,
            expected_reason_codes=[ReasonCode(code) for code in row["expected_reason_codes"].split(";") if code],
            why=row["why"],
        )
        for row in rows
    ]


def run_self_test(reading_service: InvoiceReadingService, steps: list[SelfTestStep],
                  samples_folder: Path = SAMPLE_INVOICES_FOLDER,
                  today_provider: Callable[[], date] = date.today) -> list[SelfTestStepResult]:
    """Uses its own in-memory database, so the demo data is untouched. Saved readings come from reading_service."""
    connection = open_database_connection(IN_MEMORY_DATABASE)
    try:
        reset_demo_data(connection)
        pipeline = InvoicePipelineService(connection, reading_service, today_provider)
        reference_data = ReferenceDataRepository(connection)
        run_history = RunHistoryRepository(connection)
        run_ids_by_sample: dict[str, int] = {}
        results = []
        for step in steps:
            run_result = _play_step(step, pipeline, reference_data, run_history, run_ids_by_sample, samples_folder)
            results.append(_compare(step, run_result))
        return results
    finally:
        connection.close()


def _play_step(step: SelfTestStep, pipeline: InvoicePipelineService, reference_data: ReferenceDataRepository,
               run_history: RunHistoryRepository, run_ids_by_sample: dict[str, int],
               samples_folder: Path) -> PipelineRunResult | None:
    """Mutates: run_ids_by_sample."""
    if step.action == SelfTestAction.PROCESS:
        run_result = pipeline.process_upload((samples_folder / step.target).read_bytes(), step.target)
        if run_result.run_id is not None:
            run_ids_by_sample[step.target] = run_result.run_id
        return run_result
    if step.action == SelfTestAction.LOG_RECEIPT:
        po_number, po_line, quantity = step.target.split(":")
        reference_data.log_receipt(po_number, int(po_line), Decimal(quantity))
        return None
    run_id = run_ids_by_sample[step.target]
    if step.action == SelfTestAction.RERUN:
        return pipeline.rerun(run_id)
    latest = run_history.get_latest_decision(run_id)
    suggested_po_number = latest.record.decision.suggested_po_number if latest else None
    if suggested_po_number is None:
        raise ValueError(f"Step {step.step_number}: {step.target} has no suggested PO to use.")
    return pipeline.use_po(run_id, suggested_po_number)


def _compare(step: SelfTestStep, run_result: PipelineRunResult | None) -> SelfTestStepResult:
    if step.expected_outcome is None:
        return SelfTestStepResult(step=step, actual_outcome=None, actual_reason_codes=[], is_match=True, problem=None)
    if run_result is None or run_result.record is None:
        problem = run_result.intake_problem if run_result else "no result"
        return SelfTestStepResult(step=step, actual_outcome=None, actual_reason_codes=[], is_match=False, problem=problem)
    decision = run_result.record.decision
    actual_codes = sorted({finding.code for finding in decision.findings})
    is_match = decision.outcome == step.expected_outcome and actual_codes == sorted(set(step.expected_reason_codes))
    return SelfTestStepResult(step=step, actual_outcome=decision.outcome, actual_reason_codes=actual_codes,
                              is_match=is_match, problem=None)
