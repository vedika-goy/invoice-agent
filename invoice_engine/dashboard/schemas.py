from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from invoice_engine.decision.types import Outcome
from invoice_engine.run_history.schemas import ReviewerActionType


class RunOverview(BaseModel):
    """One row of the dashboard: a run, its latest decision and what a reviewer did with it."""

    run_id: int
    file_name: str
    created_at: datetime
    vendor_name: str | None
    invoice_number: str | None
    total: Decimal | None
    currency_code: str | None
    due_date: date | None
    system_outcome: Outcome
    reviewer_action: ReviewerActionType | None  # only an action on the latest decision counts
    status_label: str  # e.g. "Needs review" or "Approved by reviewer"
    is_open: bool  # needs review or on hold, and nobody has acted on it yet
    owners: list[str]
    reason_titles: list[str]
    has_confirmed_duplicate: bool
    was_auto_approved: bool  # approved by the rules alone, with no reviewer choice involved


class DashboardSummary(BaseModel):
    processed_count: int
    auto_approved_count: int
    auto_approved_percent: Decimal
    open_count: int
    open_amount_usd: Decimal
    duplicates_caught_count: int
    duplicates_caught_amount_usd: Decimal
    reviewer_decision_count: int
    override_count: int
    exception_counts: dict[str, int]  # blocking reason title -> number of runs it applies to
    open_count_by_owner: dict[str, int]  # an open invoice with two owners counts for both
    open_amount_by_owner_usd: dict[str, Decimal]
