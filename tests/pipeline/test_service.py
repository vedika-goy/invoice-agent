"""Repeat-safety and reviewer actions, through the pipeline's public methods."""
import pytest

from invoice_engine.config import SAMPLE_INVOICES_FOLDER
from invoice_engine.decision.types import Outcome, ReasonCode
from invoice_engine.ledger.repository import LedgerRepository
from invoice_engine.pipeline.schemas import StepStatus
from invoice_engine.run_history.repository import RunHistoryRepository
from invoice_engine.run_history.schemas import ReviewerActionType


def _read_sample(file_name: str) -> bytes:
    return (SAMPLE_INVOICES_FOLDER / file_name).read_bytes()


def test_same_file_twice_opens_the_earlier_run_instead_of_deciding_again(pipeline, demo_connection):
    first = pipeline.process_upload(_read_sample("ec1_a_greenfield_600_bags.pdf"), "a.pdf")
    second = pipeline.process_upload(_read_sample("ec1_a_greenfield_600_bags.pdf"), "a-again.pdf")
    assert (second.was_already_seen, second.run_id, second.decision_id) == (True, first.run_id, first.decision_id)
    assert len(RunHistoryRepository(demo_connection).list_decisions(first.run_id)) == 1


def test_rerun_of_an_approved_invoice_is_not_compared_against_itself(pipeline, demo_connection):
    first = pipeline.process_upload(_read_sample("ec1_a_greenfield_600_bags.pdf"), "a.pdf")
    rerun = pipeline.rerun(first.run_id)
    assert (first.record.decision.outcome, rerun.record.decision.outcome) == (Outcome.APPROVED, Outcome.APPROVED)
    assert rerun.record.steps[-1].details[0].startswith("Already in the ledger")
    assert LedgerRepository(demo_connection).build_billed_to_date(excluded_run_id=None)[("PO-2041", 1)].quantity == 600


def test_approving_twice_counts_the_invoice_once(pipeline, demo_connection):
    held = pipeline.process_upload(_read_sample("ec3_northstar_bank_change.pdf"), "ec3.pdf")
    assert held.record.decision.outcome == Outcome.ON_HOLD
    pipeline.record_reviewer_action(held.run_id, ReviewerActionType.APPROVE, "Treasury confirmed by phone")
    pipeline.record_reviewer_action(held.run_id, ReviewerActionType.APPROVE, "Double click")
    billed = LedgerRepository(demo_connection).build_billed_to_date(excluded_run_id=None)
    assert billed[("PO-2072", 1)].quantity == 40
    actions = RunHistoryRepository(demo_connection).list_reviewer_actions(held.run_id)
    assert [action.system_outcome for action in actions] == [Outcome.ON_HOLD, Outcome.ON_HOLD]


def test_a_reviewer_must_give_a_reason(pipeline):
    run = pipeline.process_upload(_read_sample("price_rise_apex_cleaning.pdf"), "apex.pdf")
    with pytest.raises(ValueError):
        pipeline.record_reviewer_action(run.run_id, ReviewerActionType.REJECT, "   ")


def test_an_unreadable_file_goes_to_review_with_the_checks_skipped(pipeline):
    not_a_sample = _read_sample("happy_summit_packaging.pdf") + b"\n% changed bytes, unknown to the offline reader"
    result = pipeline.process_upload(not_a_sample, "unknown.pdf")
    assert result.record.decision.outcome == Outcome.NEEDS_REVIEW
    assert [f.code for f in result.record.decision.findings] == [ReasonCode.READING_FAILED]
    assert [step.status for step in result.record.steps[2:6]] == [StepStatus.SKIPPED] * 4


def test_a_refused_file_creates_no_run(pipeline):
    result = pipeline.process_upload(b"not a pdf", "notes.txt")
    assert (result.run_id, result.intake_problem) == (None, "The file is not a PDF.")
