"""Session state of the Process page: which run is shown, and a pipeline action requested by a button."""
from dataclasses import dataclass
from enum import StrEnum

import streamlit as st

CURRENT_RUN_ID_KEY = "current_run_id"
REQUESTED_ACTION_KEY = "requested_pipeline_action"


class PipelineActionKind(StrEnum):
    PROCESS_FILE = "process_file"
    RERUN = "rerun"
    USE_PO = "use_po"


@dataclass(frozen=True)
class PipelineActionRequest:
    kind: PipelineActionKind
    run_id: int | None = None
    po_number: str | None = None
    file_name: str | None = None
    pdf_bytes: bytes | None = None


def request_pipeline_action(request: PipelineActionRequest) -> None:
    """Used as a button on_click: the page runs the action at the top of the next rerun, so the live step
    view can render where it belongs, above the button that asked for it."""
    st.session_state[REQUESTED_ACTION_KEY] = request


def take_requested_pipeline_action() -> PipelineActionRequest | None:
    return st.session_state.pop(REQUESTED_ACTION_KEY, None)


def get_current_run_id() -> int | None:
    return st.session_state.get(CURRENT_RUN_ID_KEY)


def set_current_run_id(run_id: int | None) -> None:
    st.session_state[CURRENT_RUN_ID_KEY] = run_id
