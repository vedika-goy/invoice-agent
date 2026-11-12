from decimal import Decimal

from invoice_engine.config import SAMPLE_INVOICES_FOLDER
from invoice_engine.dashboard.service import build_dashboard_summary, build_run_overviews
from invoice_engine.run_history.repository import RunHistoryRepository
from invoice_engine.run_history.schemas import ReviewerActionType


def _process(pipeline, file_name: str):
    return pipeline.process_upload((SAMPLE_INVOICES_FOLDER / file_name).read_bytes(), file_name)


def _build(demo_connection):
    run_history = RunHistoryRepository(demo_connection)
    actions = run_history.list_reviewer_actions()
    overviews = build_run_overviews(run_history.list_runs(), run_history.list_latest_decisions(), actions)
    return overviews, build_dashboard_summary(overviews, actions)


def test_totals_count_auto_approvals_open_amounts_and_duplicates(pipeline, demo_connection):
    _process(pipeline, "happy_summit_packaging.pdf")  # approved, $943.94
    _process(pipeline, "ec3_northstar_bank_change.pdf")  # on hold, $2,656.46
    _process(pipeline, "ec2_coastal_dairy_resend_scan.pdf")  # rejected duplicate, $577.50
    overviews, summary = _build(demo_connection)
    assert (summary.processed_count, summary.auto_approved_count, summary.auto_approved_percent) == (3, 1, Decimal("33.3"))
    assert (summary.open_count, summary.open_amount_usd) == (1, Decimal("2656.46"))
    assert (summary.duplicates_caught_count, summary.duplicates_caught_amount_usd) == (1, Decimal("577.50"))
    assert summary.exception_counts == {"Bank account differs from the one on file": 1, "Confirmed duplicate": 1}
    assert (summary.open_count_by_owner, summary.open_amount_by_owner_usd) == ({"Treasury": 1}, {"Treasury": Decimal("2656.46")})


def test_runs_are_sorted_by_due_date_most_urgent_first(pipeline, demo_connection):
    _process(pipeline, "happy_summit_packaging.pdf")  # due 2026-12-03
    _process(pipeline, "ec2_coastal_dairy_same_amount.pdf")  # due 2026-11-13
    overviews, _ = _build(demo_connection)
    assert [overview.invoice_number for overview in overviews] == ["INV-00891", "SP-3352"]


def test_approving_a_held_invoice_is_an_override_and_closes_it(pipeline, demo_connection):
    held = _process(pipeline, "ec3_northstar_bank_change.pdf")
    pipeline.record_reviewer_action(held.run_id, ReviewerActionType.APPROVE, "Treasury confirmed by phone")
    overviews, summary = _build(demo_connection)
    assert (overviews[0].status_label, overviews[0].is_open) == ("Approved by reviewer", False)
    assert (summary.reviewer_decision_count, summary.override_count, summary.open_count) == (1, 1, 0)


def test_deciding_a_needs_review_invoice_is_not_an_override(pipeline, demo_connection):
    review = _process(pipeline, "price_rise_apex_cleaning.pdf")
    pipeline.record_reviewer_action(review.run_id, ReviewerActionType.REJECT, "Price rise not agreed")
    _, summary = _build(demo_connection)
    assert (summary.reviewer_decision_count, summary.override_count) == (1, 0)


def test_a_rerun_after_a_reviewer_action_reopens_the_run(pipeline, demo_connection):
    review = _process(pipeline, "price_rise_apex_cleaning.pdf")
    pipeline.record_reviewer_action(review.run_id, ReviewerActionType.REJECT, "Price rise not agreed")
    pipeline.rerun(review.run_id)
    overviews, _ = _build(demo_connection)
    assert (overviews[0].status_label, overviews[0].is_open) == ("Needs review", True)
