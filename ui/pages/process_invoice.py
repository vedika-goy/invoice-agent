"""Process an invoice: pick a sample or upload a PDF, watch every step run, then act on the decision."""
import streamlit as st

from invoice_engine.config import SAMPLE_INVOICES_FOLDER
from invoice_engine.pipeline.schemas import PipelineRunResult
from invoice_engine.utils.pdf_document import render_pdf_page_png
from invoice_engine.utils.sample_invoices import load_sample_specs
from ui.components.decision_card import render_decision_card
from ui.components.step_log import LiveStepLog, render_steps
from ui.context.engine_context import EngineContext, get_engine_context
from ui.stores.process_page_state import (
    PipelineActionKind,
    PipelineActionRequest,
    get_current_run_id,
    request_pipeline_action,
    set_current_run_id,
    take_requested_pipeline_action,
)

SAMPLE_PICKER_KEY = "sample_file_name"
UPLOADER_KEY = "uploaded_invoice"
PREVIEW_ZOOM = 1.4


@st.cache_data
def load_sample_scenarios() -> dict[str, str]:
    return {document["file_name"]: document["scenario"] for document in load_sample_specs()["documents"]}


@st.cache_data(max_entries=64)
def build_preview_png(pdf_bytes: bytes) -> bytes:
    return render_pdf_page_png(pdf_bytes, zoom=PREVIEW_ZOOM)


def request_sample_processing() -> None:
    file_name = st.session_state[SAMPLE_PICKER_KEY]
    request_pipeline_action(PipelineActionRequest(PipelineActionKind.PROCESS_FILE, file_name=file_name,
                                                  pdf_bytes=(SAMPLE_INVOICES_FOLDER / file_name).read_bytes()))


def request_upload_processing() -> None:
    uploaded_file = st.session_state.get(UPLOADER_KEY)
    if uploaded_file is not None:
        request_pipeline_action(PipelineActionRequest(PipelineActionKind.PROCESS_FILE, file_name=uploaded_file.name,
                                                      pdf_bytes=uploaded_file.getvalue()))


def render_inputs() -> None:
    sample_column, upload_column = st.columns(2, gap="medium")
    with sample_column.container(border=True, height="stretch"):
        st.markdown("**Run a sample invoice**")
        scenarios = load_sample_scenarios()
        st.selectbox("Sample invoice", options=list(scenarios), format_func=lambda file_name: scenarios[file_name],
                     key=SAMPLE_PICKER_KEY, label_visibility="collapsed")
        st.button("Process sample", icon=":material/play_arrow:", type="primary", on_click=request_sample_processing)
    with upload_column.container(border=True, height="stretch"):
        st.markdown("**Or upload your own PDF**")
        st.file_uploader("Invoice PDF", type=["pdf"], key=UPLOADER_KEY, label_visibility="collapsed")
        st.button("Process upload", icon=":material/upload:", on_click=request_upload_processing,
                  disabled=st.session_state.get(UPLOADER_KEY) is None)


def render_invoice_preview(pdf_bytes: bytes, file_name: str) -> None:
    st.caption(f":material/description: {file_name}")
    st.image(build_preview_png(pdf_bytes), width="stretch")


def run_requested_action(context: EngineContext, request: PipelineActionRequest, preview_column,
                         run_column) -> PipelineRunResult:
    if request.kind == PipelineActionKind.PROCESS_FILE:
        pdf_bytes, file_name = request.pdf_bytes, request.file_name
    else:
        stored_run = context.run_history.get_run(request.run_id)
        pdf_bytes, file_name = stored_run.pdf_bytes, stored_run.file_name
    with preview_column:
        render_invoice_preview(pdf_bytes, file_name)
    with run_column:
        st.markdown("##### :material/bolt: Live run")
        live_slot = st.empty()
        with live_slot.container():
            live_log = LiveStepLog()
            result = _call_pipeline(context, request, pdf_bytes, file_name, live_log)
            live_log.finish()
        if result.was_already_seen and result.record is not None:
            live_slot.empty()
            st.info(f"This exact file was processed before (same SHA-256 fingerprint), so run {result.run_id} opened "
                    "instead of a second decision. Re-run it below to check it against today's data.",
                    icon=":material/fingerprint:")
            render_steps(result.record.steps)
    return result


def render_stored_run(context: EngineContext, run_id: int, preview_column, run_column) -> bool:
    stored_run = context.run_history.get_run(run_id)
    latest = context.run_history.get_latest_decision(run_id)
    if stored_run is None or latest is None:
        return False
    with preview_column:
        render_invoice_preview(stored_run.pdf_bytes, stored_run.file_name)
    with run_column:
        st.markdown(f"##### :material/history: Run {run_id}: latest decision")
        render_steps(latest.record.steps)
    return True


def _call_pipeline(context: EngineContext, request: PipelineActionRequest, pdf_bytes: bytes, file_name: str,
                   live_log: LiveStepLog) -> PipelineRunResult:
    if request.kind == PipelineActionKind.PROCESS_FILE:
        return context.pipeline.process_upload(pdf_bytes, file_name, live_log.handle_step_completed)
    if request.kind == PipelineActionKind.RERUN:
        return context.pipeline.rerun(request.run_id, live_log.handle_step_completed)
    return context.pipeline.use_po(request.run_id, request.po_number, live_log.handle_step_completed)


context = get_engine_context()
st.title("Process an invoice")
st.caption("Pick a sample or upload a PDF. Each step shows what it checked and what it concluded, as it runs.")
render_inputs()

request = take_requested_pipeline_action()
if request is None and get_current_run_id() is None:
    st.info("Pick a sample invoice above to see the process run. Start with the happy path, then try the edge cases.",
            icon=":material/arrow_upward:")
    st.stop()

preview_column, run_column = st.columns([5, 7], gap="large")
# The decision goes above the steps: filled in once they finish, so the outcome is the first thing in view.
decision_slot = run_column.container()
if request is not None:
    result = run_requested_action(context, request, preview_column, run_column)
    if result.run_id is None:
        run_column.error(f"File refused: {result.intake_problem}", icon=":material/block:")
        st.stop()
    set_current_run_id(result.run_id)
elif not render_stored_run(context, get_current_run_id(), preview_column, run_column):
    set_current_run_id(None)
    st.rerun()

current_run_id = get_current_run_id()
latest_decision = context.run_history.get_latest_decision(current_run_id)
if latest_decision is None:
    # The same file arrived twice at once and the other session is still deciding it.
    run_column.warning(f"Run {current_run_id} is still being decided. Refresh in a moment.", icon=":material/hourglass:")
    st.stop()
with decision_slot:
    render_decision_card(context, current_run_id, latest_decision.decision_id, latest_decision.record)
