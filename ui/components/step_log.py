"""The step-by-step view of a run: live while the pipeline executes, or replayed from a stored decision."""
import streamlit as st

from invoice_engine.pipeline.schemas import StepResult, StepStatus
from invoice_engine.pipeline.service import PIPELINE_STEPS, RECORD_APPROVAL_STEP_NUMBER
from invoice_engine.reading.service import READ_STEP_NUMBER
from invoice_engine.utils.markdown_text import escape_markdown
from ui.components.outcome_badge import OUTCOME_ICONS

STEP_STATUS_ICONS = {
    StepStatus.PASSED: ":material/check_circle:",
    StepStatus.WARNING: ":material/warning:",
    StepStatus.FAILED: ":material/cancel:",
    StepStatus.SKIPPED: ":material/do_not_disturb_on:",
}
STEP_STATUS_COLORS = {StepStatus.PASSED: "green", StepStatus.WARNING: "orange", StepStatus.FAILED: "red",
                      StepStatus.SKIPPED: "gray"}
RUNNING_LABELS = {READ_STEP_NUMBER: "Claude is reading the invoice (scans are read twice)…"}


def render_step(step: StepResult) -> None:
    """Steps that found a problem open by default, so the reviewer sees them without clicking."""
    color = STEP_STATUS_COLORS[step.status]
    is_expanded = step.status in (StepStatus.WARNING, StepStatus.FAILED)
    with st.expander(f":{color}[**{step.step_number}. {step.title}**]", icon=STEP_STATUS_ICONS[step.status],
                     expanded=is_expanded):
        for detail in step.details:
            st.markdown(f"- {escape_markdown(detail)}")
        for finding in step.findings:
            icon = OUTCOME_ICONS[finding.outcome] if finding.outcome else ":material/info:"
            st.markdown(f"{icon} **{finding.title}**: {escape_markdown(finding.explanation)}")


def render_steps(steps: list[StepResult]) -> None:
    for step in steps:
        render_step(step)


class LiveStepLog:
    """Lists every step as waiting, then fills each one in the moment the pipeline reports it."""

    def __init__(self) -> None:
        self._placeholders = {}
        for step_number, title in PIPELINE_STEPS:
            self._placeholders[step_number] = st.empty()
            self._show_waiting(step_number, title)
        self._completed_step_numbers: set[int] = set()
        self._show_running(PIPELINE_STEPS[0][0])

    # Fired by: InvoicePipelineService on_step_completed
    def handle_step_completed(self, step: StepResult) -> None:
        self._completed_step_numbers.add(step.step_number)
        with self._placeholders[step.step_number].container():
            render_step(step)
        next_step_numbers = [number for number, _ in PIPELINE_STEPS if number > step.step_number]
        if next_step_numbers:
            self._show_running(next_step_numbers[0])

    def finish(self) -> None:
        """Steps that never ran (the approval record when nothing was approved) are marked as not needed."""
        for step_number, title in PIPELINE_STEPS:
            if step_number not in self._completed_step_numbers:
                label = "only runs when the invoice is approved" if step_number == RECORD_APPROVAL_STEP_NUMBER else "not run"
                self._placeholders[step_number].markdown(f":gray[:material/remove: {step_number}. {title}: {label}]")

    def _show_waiting(self, step_number: int, title: str) -> None:
        self._placeholders[step_number].markdown(f":gray[:material/radio_button_unchecked: {step_number}. {title}]")

    def _show_running(self, step_number: int) -> None:
        title = dict(PIPELINE_STEPS)[step_number]
        label = RUNNING_LABELS.get(step_number, "running…")
        self._placeholders[step_number].markdown(f":blue[:material/progress_activity: **{step_number}. {title}**: {label}]")
