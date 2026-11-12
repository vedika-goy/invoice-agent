"""Dashboard: what an AP manager sees across runs, with each run's full audit trail one click away."""
import pandas
import streamlit as st

from invoice_engine.dashboard.schemas import DashboardSummary, RunOverview
from invoice_engine.dashboard.service import build_dashboard_summary, build_run_overviews, is_override
from invoice_engine.decision.types import OUTCOME_LABELS
from invoice_engine.run_history.schemas import ReviewerActionType
from invoice_engine.utils.markdown_text import escape_markdown
from invoice_engine.utils.money import format_money
from ui.components.decision_card import TRIGGER_LABELS
from ui.components.outcome_badge import OUTCOME_DOTS, render_outcome_badge
from ui.components.step_log import render_steps
from ui.context.engine_context import EngineContext, get_engine_context
from ui.stores.process_page_state import set_current_run_id

REVIEWER_DOTS = {ReviewerActionType.APPROVE: "✅", ReviewerActionType.REJECT: "⛔"}
NO_OWNER_LABEL = "Nobody (done)"


def render_totals(summary: DashboardSummary) -> None:
    columns = st.columns(5)
    columns[0].metric("Invoices processed", summary.processed_count, border=True)
    columns[1].metric("Auto-approved", f"{summary.auto_approved_percent}%", border=True,
                      help=f"{summary.auto_approved_count} invoices approved by the rules alone.")
    columns[2].metric("Waiting on someone", format_money(summary.open_amount_usd), border=True,
                      help=f"{summary.open_count} invoices in review or on hold that nobody has acted on yet.")
    columns[3].metric("Duplicates caught", format_money(summary.duplicates_caught_amount_usd), border=True,
                      help=f"{summary.duplicates_caught_count} invoices that would have been paid twice.")
    columns[4].metric("Human overrides", f"{summary.override_count} of {summary.reviewer_decision_count}", border=True,
                      help="Reviewer decisions that went against the process: approving what it rejected or held, "
                           "or rejecting what it approved. Keeps the approval rate honest.")


def render_exceptions_and_open_work(summary: DashboardSummary) -> None:
    exceptions_column, owners_column = st.columns([3, 2], gap="large")
    with exceptions_column:
        st.markdown("##### Exceptions by reason")
        if summary.exception_counts:
            st.dataframe(
                pandas.DataFrame({"Reason": list(summary.exception_counts),
                                  "Invoices": list(summary.exception_counts.values())}),
                hide_index=True, width="stretch",
                column_config={"Invoices": st.column_config.ProgressColumn(
                    "Invoices", format="%d", min_value=0, max_value=max(summary.processed_count, 1))})
        else:
            st.caption("No exceptions yet: every invoice so far passed every check.")
    with owners_column:
        st.markdown("##### Open work by owner")
        if summary.open_count_by_owner:
            st.dataframe(
                pandas.DataFrame({"Owner": list(summary.open_count_by_owner),
                                  "Invoices": list(summary.open_count_by_owner.values()),
                                  "Amount": [float(summary.open_amount_by_owner_usd[owner])
                                             for owner in summary.open_count_by_owner]}),
                hide_index=True, width="stretch",
                column_config={"Amount": st.column_config.NumberColumn(format="dollar")})
        else:
            st.caption("Nothing waiting on anyone.")


def build_runs_table(overviews: list[RunOverview]) -> pandas.DataFrame:
    return pandas.DataFrame([
        {
            "Due": overview.due_date,
            "Status": f"{REVIEWER_DOTS.get(overview.reviewer_action, OUTCOME_DOTS[overview.system_outcome])} "
                      f"{overview.status_label}",
            "Vendor": overview.vendor_name or "—",
            "Invoice": overview.invoice_number or "—",
            "Amount": float(overview.total) if overview.total is not None else None,
            "Who handles it": ", ".join(overview.owners) if overview.is_open else NO_OWNER_LABEL,
            "Reasons": ", ".join(overview.reason_titles) or "All checks passed",
            "Run": overview.run_id,
            "File": overview.file_name,
        }
        for overview in overviews
    ])


def filter_overviews(overviews: list[RunOverview]) -> list[RunOverview]:
    status_column, owner_column = st.columns(2)
    statuses = sorted({overview.status_label for overview in overviews})
    owners = sorted({owner for overview in overviews if overview.is_open for owner in overview.owners})
    selected_statuses = status_column.multiselect("Status", statuses, placeholder="All statuses")
    selected_owners = owner_column.multiselect("Who handles it (open invoices)", owners, placeholder="Everyone")
    return [
        overview for overview in overviews
        if (not selected_statuses or overview.status_label in selected_statuses)
        and (not selected_owners or (overview.is_open and set(overview.owners) & set(selected_owners)))
    ]


def render_audit_trail(context: EngineContext, run_id: int) -> None:
    decisions = context.run_history.list_decisions(run_id)
    reviewer_actions = context.run_history.list_reviewer_actions(run_id)
    title_column, open_column = st.columns([4, 1], vertical_alignment="center")
    title_column.markdown(f"#### Audit trail: run {run_id}")
    if open_column.button("Open in Process page", icon=":material/open_in_new:", width="stretch"):
        set_current_run_id(run_id)
        st.switch_page("ui/pages/process_invoice.py")
    events = [(stored.created_at, "decision", stored) for stored in decisions]
    events += [(action.created_at, "action", action) for action in reviewer_actions]
    for _, kind, event in sorted(events, key=lambda item: item[0]):
        with st.container(border=True):
            if kind == "decision":
                record = event.record
                header_column, badge_column = st.columns([4, 1])
                header_column.markdown(f"**{event.created_at:%Y-%m-%d %H:%M} UTC · decision ({TRIGGER_LABELS[record.trigger]})**"
                                       f" · policy {record.decision.policy_version}")
                with badge_column:
                    render_outcome_badge(record.decision.outcome)
                render_steps(record.steps)
            else:
                verdict = "approved" if event.action == ReviewerActionType.APPROVE else "rejected"
                override_note = " · override" if is_override(event) else ""
                st.markdown(f"**{event.created_at:%Y-%m-%d %H:%M} UTC · reviewer {verdict}**{override_note} "
                            f"(process said {OUTCOME_LABELS[event.system_outcome]}): "
                            f"{escape_markdown(event.reviewer_note)}")


context = get_engine_context()
run_history = context.run_history
reviewer_actions = run_history.list_reviewer_actions()
overviews = build_run_overviews(run_history.list_runs(), run_history.list_latest_decisions(), reviewer_actions)
summary = build_dashboard_summary(overviews, reviewer_actions)

st.title("Dashboard")
st.caption("Every invoice processed, most urgent first. Select a row to see its full step-by-step audit trail.")
if not overviews:
    st.info("No invoices processed yet.", icon=":material/inbox:")
    st.page_link("ui/pages/process_invoice.py", label="Process an invoice", icon=":material/play_circle:")
    st.stop()

render_totals(summary)
render_exceptions_and_open_work(summary)

st.markdown("##### All runs")
filtered_overviews = filter_overviews(overviews)
selection_event = st.dataframe(
    build_runs_table(filtered_overviews), hide_index=True, width="stretch", on_select="rerun",
    selection_mode="single-row", key="runs_table",
    column_config={
        "Due": st.column_config.DateColumn("Due", format="YYYY-MM-DD"),
        "Amount": st.column_config.NumberColumn("Amount", format="dollar"),
        "Run": st.column_config.NumberColumn("Run", format="%d"),
    },
)
selected_rows = selection_event.selection.rows
if selected_rows:
    render_audit_trail(context, filtered_overviews[selected_rows[0]].run_id)
else:
    st.caption(":material/touch_app: Select a row to open its audit trail.")
