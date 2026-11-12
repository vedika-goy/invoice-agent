"""How it decides: the process map, the rules and why each exists, the design choices, the policy, the data
behind the checks (editable live), and the self-test."""
from datetime import date
from decimal import Decimal

import pandas
import pydantic
import streamlit as st

from invoice_engine.config import DIAGRAMS_FOLDER
from invoice_engine.decision.config import REASON_RULES
from invoice_engine.decision.types import OUTCOME_LABELS, OUTCOME_SEVERITY_RANK
from invoice_engine.policy.config import (
    APPROVAL_LIMIT_USD,
    DUPLICATE_AMOUNT_TOLERANCE_USD,
    DUPLICATE_WINDOW_DAYS,
    LINE_DESCRIPTION_MIN_SIMILARITY_PERCENT,
    MAX_PAGE_COUNT,
    MAX_UPLOAD_SIZE_BYTES,
    POLICY_VERSION,
    PRICE_TOLERANCE_PERCENT,
    ROUNDING_TOLERANCE_PER_LINE_USD,
    UNPLANNED_CHARGE_ALLOWANCE_USD,
    VENDOR_NAME_MIN_SIMILARITY_PERCENT,
)
from invoice_engine.reference_data.schemas import PurchaseOrderLine, PurchaseOrderStatus, Vendor, VendorStatus
from invoice_engine.self_test.service import SelfTestStepResult, load_self_test_steps, run_self_test
from invoice_engine.utils.money import format_money, format_percent, format_quantity_with_unit
from ui.components.outcome_badge import OUTCOME_DOTS
from ui.context.engine_context import EngineContext, get_engine_context

VENDORS_EDITOR_KEY = "vendors_editor"
PO_LINES_EDITOR_KEY = "po_lines_editor"
BYTES_PER_MEGABYTE = 1024 * 1024
# Display labels for the editable tables; the column names stay the model's field names.
COLUMN_LABELS = {
    "vendor_id": "Vendor", "vendor_name": "Name", "tax_id": "Tax ID", "status": "Status", "currency": "Currency",
    "bank_account_last4": "Bank (last 4)", "payment_terms_days": "Terms (days)", "phone_on_file": "Phone on file",
    "remit_email": "Remit email", "po_number": "PO", "po_line": "Line", "item_code": "Item",
    "description": "Description", "unit_of_measure": "Unit", "quantity_ordered": "Ordered",
    "quantity_received": "Received", "unit_price": "Unit price", "requested_by": "Requested by", "po_date": "PO date",
}

DESIGN_DECISIONS = [
    ("AI reads the invoice; rules decide", "Let the AI decide end to end",
     "Decisions about money must be repeatable and explainable to an auditor."),
    ("Check the AI's reading with code", "Trust the AI's own confidence score",
     "Models can be confidently wrong. Quotes, arithmetic and a second reading can be verified."),
    ("Run every check, then decide once", "Stop at the first problem",
     "The reviewer sees every issue at once, instead of fixing one and then finding the next."),
    ("Send each exception to a named owner, with what would unblock it", "One generic review queue",
     "Treasury verifies bank details, Receiving confirms deliveries: each person knows their next action."),
    ("A bank-detail change is always held, however clean the rest is", "Score it as one risk among many",
     "A wrong payment costs far more than a phone call. Some checks shouldn't be outweighed by others."),
    ("Check the total billed so far against the PO and the goods received", "Compare each invoice with the PO total",
     "Vendors split invoices. One-at-a-time checks would approve three invoices that together over-bill."),
    ("Suggest a PO when none is given, but don't approve on it", "Reject invoices without a PO, or auto-match",
     "Rejecting creates busywork; auto-matching risks paying against the wrong order. When two POs fit, suggest neither."),
    ("Auto-approve only when every check passes", "Approve when most checks pass",
     "The worst mistake is a wrong approval. A few extra reviews are cheap; a duplicate or fraudulent payment isn't."),
    ("Explanations come from fixed templates", "Have the AI write each explanation",
     "The same reason is always worded the same way, and a template can't invent a detail."),
    ("Same file twice opens the earlier run (SHA-256 fingerprint); readings are saved",
     "Process every upload as new",
     "A re-upload or double click can never create a second approval, and re-runs give the same reading."),
    ("Track how often reviewers override the system", "Only track the auto-approval rate",
     "An approval rate can look good while the decisions are wrong. Overrides show whether people trust them."),
]
ASSUMPTIONS = [
    "The policy values are my assumptions; a real company sets them in its AP policy, and they live in one file.",
    "PO prices are before tax. Invoices with tax-inclusive prices are converted before comparing.",
    "Goods received are logged on the PO line. Invoices are paid only for what has arrived.",
    "Vendor bank accounts are kept as their last 4 digits; a change is verified by calling the number on file.",
    "Approved invoices count toward billed-to-date and duplicate checks straight away.",
    "All vendors and POs are in USD; a different currency goes to review rather than being converted.",
]


def render_process_map() -> None:
    map_column, notes_column = st.columns([3, 2], gap="large")
    map_column.image(str(DIAGRAMS_FOLDER / "process-pipeline.svg"), width="stretch")
    with notes_column:
        st.markdown("#### AI reads. Rules decide.")
        st.markdown(
            "- **Claude only reads**: every field, with the exact text it came from.\n"
            "- **Code checks the reading**: each value must be printed in the PDF, the numbers must add up, "
            "and scans are read twice and compared.\n"
            "- **Plain rules decide**, so the same invoice always gets the same answer, with reasons an auditor "
            "can check.\n"
            "- **Repeat-safe**: the same file opens its earlier run; re-runs reuse the saved reading; an approval "
            "is recorded once per vendor and invoice number.")
        st.image(str(DIAGRAMS_FOLDER / "high-level-design.svg"), width="stretch")


def render_rules() -> None:
    st.caption("When several rules fire, the most serious outcome wins, and every reason is still shown.")
    ordered_rules = sorted(REASON_RULES.values(),
                           key=lambda rule: -OUTCOME_SEVERITY_RANK[rule.outcome] if rule.outcome else 1)
    st.dataframe(pandas.DataFrame([
        {"Reason": rule.title,
         "Outcome": f"{OUTCOME_DOTS[rule.outcome]} {OUTCOME_LABELS[rule.outcome]}" if rule.outcome else "⚪ Note only",
         "Who handles it": rule.owner.value if rule.owner else "—",
         "Why this rule exists": rule.why}
        for rule in ordered_rules
    ]), hide_index=True, width="stretch", height=560)


def render_design_decisions() -> None:
    st.caption("Each choice, the option I turned down, and why.")
    st.table(pandas.DataFrame(DESIGN_DECISIONS, columns=["Decision", "Option turned down", "Why"]))


def render_policy() -> None:
    st.markdown(f"**Policy version {POLICY_VERSION}**: every decision records the version it used.")
    st.table(pandas.DataFrame([
        ("Price tolerance", format_percent(PRICE_TOLERANCE_PERCENT), "A line priced up to this much above the PO passes."),
        ("Charges not on the PO", format_money(UNPLANNED_CHARGE_ALLOWANCE_USD), "Freight or fuel up to this passes with a note."),
        ("Duplicate window", f"{DUPLICATE_WINDOW_DAYS} days", "Same vendor and amount within this window is a possible duplicate."),
        ("Duplicate amount tolerance", format_money(DUPLICATE_AMOUNT_TOLERANCE_USD), "Amounts this close count as the same."),
        ("Rounding tolerance", f"{format_money(ROUNDING_TOLERANCE_PER_LINE_USD)} per line", "Allowed difference when numbers are added up."),
        ("Approval limit", format_money(APPROVAL_LIMIT_USD), "Above this, the AP manager gives a second approval."),
        ("Vendor name match", f"{VENDOR_NAME_MIN_SIMILARITY_PERCENT}% similar", "Below this, the vendor isn't recognised."),
        ("Line description match", f"{LINE_DESCRIPTION_MIN_SIMILARITY_PERCENT}% similar", "Used to match lines to a PO without item codes."),
        ("Upload limit", f"{MAX_UPLOAD_SIZE_BYTES // BYTES_PER_MEGABYTE} MB, {MAX_PAGE_COUNT} pages", "Larger files are refused at intake."),
    ], columns=["Setting", "Value", "What it means"]))
    st.markdown("**Assumptions**")
    st.markdown("\n".join(f"- {assumption}" for assumption in ASSUMPTIONS))


def render_data(context: EngineContext) -> None:
    st.caption("This is the data every check compares against. Change it live, then re-run an invoice to see the "
               "decision change: log a delivery for EC-1, or change a bank account.")
    _render_delivery_form(context)
    st.markdown("##### Vendors")
    vendors_frame = pandas.DataFrame([vendor.model_dump(mode="json") for vendor in context.reference_data.list_vendors()])
    edited_vendors = st.data_editor(vendors_frame, key=VENDORS_EDITOR_KEY, hide_index=True, width="stretch",
                                    disabled=["vendor_id"], column_config={
                                        **COLUMN_LABELS,
                                        "status": st.column_config.SelectboxColumn(
                                            "Status", options=[s.value for s in VendorStatus])})
    st.markdown("##### PO lines")
    po_frame = pandas.DataFrame([_to_po_row(line) for line in context.reference_data.list_purchase_order_lines()])
    edited_po_lines = st.data_editor(po_frame, key=PO_LINES_EDITOR_KEY, hide_index=True, width="stretch",
                                     disabled=["po_number", "po_line", "vendor_id"], column_config={
                                         **COLUMN_LABELS,
                                         "status": st.column_config.SelectboxColumn(
                                             "Status", options=[s.value for s in PurchaseOrderStatus])})
    if st.button("Save changes", icon=":material/save:", type="primary"):
        _save_reference_data(context, edited_vendors, edited_po_lines)
    st.markdown("##### Ledger: invoices already paid or approved")
    st.dataframe(pandas.DataFrame([
        {"Vendor": invoice.vendor_id, "Invoice": invoice.invoice_number, "Date": invoice.invoice_date,
         "Total": float(invoice.invoice_total), "Status": invoice.status_label,
         "PO lines": ", ".join(f"{line.po_number}/{line.po_line} × {line.quantity}" for line in invoice.lines)}
        for invoice in context.ledger.list_invoices()
    ]), hide_index=True, width="stretch",
        column_config={"Total": st.column_config.NumberColumn(format="dollar")})


def _render_delivery_form(context: EngineContext) -> None:
    open_lines = [line for line in context.reference_data.list_purchase_order_lines()
                  if line.status == PurchaseOrderStatus.OPEN and line.quantity_received < line.quantity_ordered]
    if not open_lines:
        return
    with st.form("log_delivery_form"):
        st.markdown("**Log a delivery** (what Receiving does when goods arrive)")
        line_column, quantity_column, submit_column = st.columns([4, 2, 1], vertical_alignment="bottom")
        selected_line = line_column.selectbox(
            "PO line", open_lines,
            format_func=lambda line: f"{line.po_number} line {line.po_line} · {line.description} · received "
                                     f"{format_quantity_with_unit(line.quantity_received, line.unit_of_measure)} of "
                                     f"{format_quantity_with_unit(line.quantity_ordered, line.unit_of_measure)}")
        quantity = quantity_column.number_input("Quantity received now", min_value=1, step=1, value=1)
        if submit_column.form_submit_button("Log", icon=":material/local_shipping:", width="stretch"):
            updated_line = context.reference_data.log_receipt(selected_line.po_number, selected_line.po_line, Decimal(quantity))
            st.toast(f"Logged {quantity} on {updated_line.po_number} line {updated_line.po_line}. "
                     "Re-run the held invoice to see it clear.", icon=":material/local_shipping:")
            st.rerun()


def _to_po_row(line: PurchaseOrderLine) -> dict:
    row = line.model_dump(mode="json")
    for field_name in ("quantity_ordered", "quantity_received", "unit_price"):
        row[field_name] = float(getattr(line, field_name))
    row["po_date"] = line.po_date
    return row


def _save_reference_data(context: EngineContext, vendors_frame: pandas.DataFrame, po_frame: pandas.DataFrame) -> None:
    try:
        vendors = [Vendor.model_validate(row) for row in vendors_frame.to_dict("records")]
        po_lines = [PurchaseOrderLine.model_validate({**row, **{name: Decimal(str(row[name])) for name in (
            "quantity_ordered", "quantity_received", "unit_price")}}) for row in po_frame.to_dict("records")]
    except (pydantic.ValidationError, ValueError, ArithmeticError) as error:
        st.error(f"Not saved: a value is invalid. {error}", icon=":material/error:")
        return
    context.reference_data.replace_all(vendors, po_lines)
    # The editors hold their edits by key; clear them so they show the saved data rather than re-applying edits.
    st.session_state.pop(VENDORS_EDITOR_KEY, None)
    st.session_state.pop(PO_LINES_EDITOR_KEY, None)
    st.toast("Saved. Re-run an invoice to use the new data.", icon=":material/save:")
    st.rerun()


def render_self_test(context: EngineContext) -> None:
    st.caption("Plays every sample in samples/expected.csv, in order, on a throwaway copy of the data, and compares "
               "each outcome and its reasons with what I expected. Your demo data isn't touched. Saved readings are "
               "reused, so Claude is only called for samples it hasn't read yet.")
    if not st.button("Run self-test", icon=":material/fact_check:", type="primary"):
        return
    with st.spinner("Running every sample…"):
        results = run_self_test(context.reading_service, load_self_test_steps(), today_provider=date.today)
    match_count = sum(result.is_match for result in results)
    if match_count == len(results):
        st.success(f"All {len(results)} steps match the expected results.", icon=":material/verified:")
    else:
        st.error(f"{len(results) - match_count} of {len(results)} steps don't match.", icon=":material/error:")
    st.dataframe(pandas.DataFrame([_to_self_test_row(result) for result in results]), hide_index=True, width="stretch")


def _to_self_test_row(result: SelfTestStepResult) -> dict:
    step = result.step
    return {
        "Match": "✅" if result.is_match else "❌",
        "Step": step.step_number,
        "Action": step.action.value.replace("_", " "),
        "Sample": step.target,
        "Expected": OUTCOME_LABELS[step.expected_outcome] if step.expected_outcome else "(data change)",
        "Actual": OUTCOME_LABELS[result.actual_outcome] if result.actual_outcome else "(done)",
        "Reasons": ", ".join(code.value for code in result.actual_reason_codes),
        "Why I expected it": step.why,
    }


context = get_engine_context()
st.title("How it decides")
st.caption("The thinking behind every decision: what runs, which rules apply and why, and the data they check against.")
process_tab, rules_tab, decisions_tab, policy_tab, data_tab, self_test_tab = st.tabs(
    ["Process map", "Rules", "Design decisions", "Policy and assumptions", "Data", "Self-test"])
with process_tab:
    render_process_map()
with rules_tab:
    render_rules()
with decisions_tab:
    render_design_decisions()
with policy_tab:
    render_policy()
with data_tab:
    render_data(context)
with self_test_tab:
    render_self_test(context)
