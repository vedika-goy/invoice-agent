"""One decision: the outcome, why, who handles it, what unblocks it, and the reviewer's approve or reject."""
import streamlit as st

from invoice_engine.decision.schemas import Finding
from invoice_engine.decision.types import OUTCOME_LABELS, Outcome
from invoice_engine.pipeline.schemas import DecisionRecord, DecisionTrigger
from invoice_engine.run_history.schemas import ReviewerActionType
from invoice_engine.utils.markdown_text import escape_markdown
from invoice_engine.utils.money import format_money
from ui.components.outcome_badge import OUTCOME_HEADLINES, OUTCOME_ICONS, render_outcome_badge
from ui.context.engine_context import EngineContext
from ui.stores.process_page_state import PipelineActionKind, PipelineActionRequest, request_pipeline_action

TRIGGER_LABELS = {
    DecisionTrigger.UPLOAD: "first run",
    DecisionTrigger.RERUN: "re-run on current data",
    DecisionTrigger.USE_SUGGESTED_PO: "re-run with the PO the reviewer chose",
}


def render_decision_card(context: EngineContext, run_id: int, decision_id: int, record: DecisionRecord) -> None:
    decision = record.decision
    with st.container(border=True):
        header_column, rerun_column = st.columns([3, 2], vertical_alignment="center")
        with header_column:
            render_outcome_badge(decision.outcome)
            st.markdown(f"#### {OUTCOME_HEADLINES[decision.outcome]}")
        rerun_column.button(
            "Re-run checks", icon=":material/refresh:", width="stretch", on_click=request_pipeline_action,
            args=(PipelineActionRequest(PipelineActionKind.RERUN, run_id=run_id),),
            help="Runs every check again on the current data, reusing the saved reading (no AI call).")
        _render_key_facts(record)
        _render_reasons(decision.findings)
        _render_suggested_po(run_id, decision.suggested_po_number)
        _render_vendor_email(decision.vendor_email_draft)
        st.caption(f"Run {run_id} · decision {decision_id} · {TRIGGER_LABELS[record.trigger]} · "
                   f"policy {decision.policy_version}")
    _render_reviewer_section(context, run_id, decision_id, decision.outcome)


def _render_review_form(decision_id: int, system_outcome: Outcome) -> tuple[bool, bool, str]:
    """Returns (approve clicked, reject clicked, reason)."""
    with st.form(key=f"review_form_{decision_id}"):
        st.caption(f"The process recommends **{OUTCOME_LABELS[system_outcome]}**. Your decision is recorded next to it, "
                   "with your reason.")
        reviewer_note = st.text_input("Reason (required)", placeholder="e.g. Treasury confirmed the new account by phone")
        approve_column, reject_column = st.columns(2)
        is_approved = approve_column.form_submit_button("Approve", icon=":material/check:", type="primary", width="stretch")
        is_rejected = reject_column.form_submit_button("Reject", icon=":material/close:", width="stretch")
    return is_approved, is_rejected, reviewer_note


def _render_key_facts(record: DecisionRecord) -> None:
    summary = record.invoice_summary
    facts = [
        ("Amount", format_money(summary.total, summary.currency_code) if summary.total is not None else "—"),
        ("Due", summary.due_date.isoformat() if summary.due_date else "—"),
        ("Vendor", summary.vendor_name or "—"),
        ("Invoice", summary.invoice_number or "—"),
        ("PO", summary.po_number or "—"),
    ]
    for column, (label, value) in zip(st.columns([2, 2, 3, 2, 2]), facts, strict=True):
        column.caption(label)
        column.markdown(f"**{escape_markdown(value)}**")


def _render_reasons(findings: list[Finding]) -> None:
    blocking_findings = [finding for finding in findings if finding.outcome is not None]
    notes = [finding for finding in findings if finding.outcome is None]
    if blocking_findings:
        st.markdown("**Why**")
        for finding in blocking_findings:
            _render_reason(finding)
    for note in notes:
        st.caption(f":material/info: {escape_markdown(note.explanation)}")


def _render_reason(finding: Finding) -> None:
    with st.container(border=True):
        title_column, owner_column = st.columns([3, 2])
        title_column.markdown(f"{OUTCOME_ICONS[finding.outcome]} **{finding.title}**")
        owner = finding.owner_name or (finding.owner.value if finding.owner else "AP clerk")
        owner_column.markdown(f":material/person: {escape_markdown(owner)}")
        st.markdown(escape_markdown(finding.explanation))
        if finding.measured and finding.limit:
            st.caption(f"Found **{escape_markdown(finding.measured)}** · limit **{escape_markdown(finding.limit)}**")
        if finding.unblock_action:
            st.markdown(f":material/lock_open: **To unblock:** {escape_markdown(finding.unblock_action)}")


def _render_suggested_po(run_id: int, suggested_po_number: str | None) -> None:
    if suggested_po_number is None:
        return
    with st.container(border=True):
        st.markdown(f":material/lightbulb: **Suggested PO: {suggested_po_number}**. A suggestion never releases "
                    "money on its own; using it re-runs every check against that PO.")
        st.button(f"Use {suggested_po_number}", icon=":material/link:", type="primary", on_click=request_pipeline_action,
                  args=(PipelineActionRequest(PipelineActionKind.USE_PO, run_id=run_id, po_number=suggested_po_number),))


def _render_vendor_email(vendor_email_draft: str | None) -> None:
    if vendor_email_draft is None:
        return
    with st.expander("Email to the vendor (draft, ready to copy)", icon=":material/mail:", expanded=True):
        st.code(vendor_email_draft, language=None, wrap_lines=True)


def _render_reviewer_section(context: EngineContext, run_id: int, decision_id: int, system_outcome: Outcome) -> None:
    actions_on_this_decision = [action for action in context.run_history.list_reviewer_actions(run_id)
                                if action.decision_id == decision_id]
    st.markdown("##### Reviewer decision")
    if actions_on_this_decision:
        action = actions_on_this_decision[-1]
        label = "Approved" if action.action == ReviewerActionType.APPROVE else "Rejected"
        message = f"{label} by reviewer: {escape_markdown(action.reviewer_note)}"
        (st.success if action.action == ReviewerActionType.APPROVE else st.error)(message, icon=":material/how_to_reg:")
        st.caption(f"The process had recommended {OUTCOME_LABELS[action.system_outcome]}. Both are kept in the audit trail.")
        return
    if system_outcome == Outcome.APPROVED:
        # Nothing to decide on an approval; an override stays possible but out of the way.
        with st.expander("Override this approval", icon=":material/gavel:"):
            is_approved, is_rejected, reviewer_note = _render_review_form(decision_id, system_outcome)
    else:
        is_approved, is_rejected, reviewer_note = _render_review_form(decision_id, system_outcome)
    if not (is_approved or is_rejected):
        return
    action_type = ReviewerActionType.APPROVE if is_approved else ReviewerActionType.REJECT
    try:
        context.pipeline.record_reviewer_action(run_id, action_type, reviewer_note)
    except ValueError as error:
        st.error(str(error), icon=":material/edit_note:")
        return
    st.toast(f"{'Approved' if is_approved else 'Rejected'} and recorded.", icon=":material/how_to_reg:")
    st.rerun()
