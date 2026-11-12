"""What the AP manager sees across runs: totals, exceptions by reason, and one row per run."""
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

from invoice_engine.dashboard.schemas import DashboardSummary, RunOverview
from invoice_engine.decision.types import OUTCOME_LABELS, Outcome, ReasonCode
from invoice_engine.pipeline.schemas import DecisionTrigger
from invoice_engine.run_history.schemas import ReviewerAction, ReviewerActionType, RunListing, StoredDecision

OPEN_OUTCOMES = {Outcome.NEEDS_REVIEW, Outcome.ON_HOLD}
REVIEWER_STATUS_LABELS = {ReviewerActionType.APPROVE: "Approved by reviewer", ReviewerActionType.REJECT: "Rejected by reviewer"}


def is_override(action: ReviewerAction) -> bool:
    """A reviewer overrides the process when they approve what it rejected or held, or reject what it approved.
    Approving or rejecting a "Needs review" invoice is the judgment call the process asked for, not an override."""
    if action.action == ReviewerActionType.APPROVE:
        return action.system_outcome in {Outcome.REJECTED, Outcome.ON_HOLD}
    return action.system_outcome == Outcome.APPROVED


def build_run_overviews(runs: list[RunListing], latest_decisions: list[StoredDecision],
                        reviewer_actions: list[ReviewerAction]) -> list[RunOverview]:
    """Runs without a decision yet are left out. Sorted by due date, most urgent first; no due date goes last."""
    decisions_by_run_id = {stored.run_id: stored for stored in latest_decisions}
    latest_action_by_decision_id = {action.decision_id: action for action in reviewer_actions}
    overviews = []
    for run in runs:
        stored = decisions_by_run_id.get(run.run_id)
        if stored is None:
            continue
        overviews.append(_build_run_overview(run, stored, latest_action_by_decision_id.get(stored.decision_id)))
    return sorted(overviews, key=lambda overview: (overview.due_date is None, overview.due_date, overview.run_id))


def build_dashboard_summary(overviews: list[RunOverview], reviewer_actions: list[ReviewerAction]) -> DashboardSummary:
    processed_count = len(overviews)
    auto_approved_count = sum(1 for overview in overviews if overview.was_auto_approved)
    open_overviews = [overview for overview in overviews if overview.is_open]
    duplicate_overviews = [overview for overview in overviews if overview.has_confirmed_duplicate]
    exception_counts = Counter(title for overview in overviews for title in overview.reason_titles)
    open_count_by_owner: Counter[str] = Counter()
    open_amount_by_owner_usd: dict[str, Decimal] = {}
    for overview in open_overviews:
        for owner in overview.owners:
            open_count_by_owner[owner] += 1
            open_amount_by_owner_usd[owner] = open_amount_by_owner_usd.get(owner, Decimal(0)) + (overview.total or 0)
    auto_approved_percent = (
        (Decimal(auto_approved_count) * 100 / processed_count).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if processed_count else Decimal(0)
    )
    return DashboardSummary(
        processed_count=processed_count,
        auto_approved_count=auto_approved_count,
        auto_approved_percent=auto_approved_percent,
        open_count=len(open_overviews),
        open_amount_usd=_sum_totals(open_overviews),
        duplicates_caught_count=len(duplicate_overviews),
        duplicates_caught_amount_usd=_sum_totals(duplicate_overviews),
        reviewer_decision_count=len(reviewer_actions),
        override_count=sum(1 for action in reviewer_actions if is_override(action)),
        exception_counts=dict(exception_counts.most_common()),
        open_count_by_owner=dict(open_count_by_owner.most_common()),
        open_amount_by_owner_usd=open_amount_by_owner_usd,
    )


def _build_run_overview(run: RunListing, stored: StoredDecision, action: ReviewerAction | None) -> RunOverview:
    record = stored.record
    decision, summary = record.decision, record.invoice_summary
    blocking_findings = [finding for finding in decision.findings if finding.outcome is not None]
    status_label = REVIEWER_STATUS_LABELS[action.action] if action else OUTCOME_LABELS[decision.outcome]
    return RunOverview(
        run_id=run.run_id,
        file_name=run.file_name,
        created_at=run.created_at,
        vendor_name=summary.vendor_name,
        invoice_number=summary.invoice_number,
        total=summary.total,
        currency_code=summary.currency_code,
        due_date=summary.due_date,
        system_outcome=decision.outcome,
        reviewer_action=action.action if action else None,
        status_label=status_label,
        is_open=action is None and decision.outcome in OPEN_OUTCOMES,
        owners=decision.owners,
        reason_titles=[finding.title for finding in blocking_findings],
        has_confirmed_duplicate=any(finding.code == ReasonCode.DUPLICATE_CONFIRMED for finding in blocking_findings),
        was_auto_approved=decision.outcome == Outcome.APPROVED and record.trigger != DecisionTrigger.USE_SUGGESTED_PO,
    )


def _sum_totals(overviews: list[RunOverview]) -> Decimal:
    return sum((overview.total for overview in overviews if overview.total is not None), Decimal(0))
