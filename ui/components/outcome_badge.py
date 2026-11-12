"""How each outcome looks everywhere in the app."""
import streamlit as st

from invoice_engine.decision.types import OUTCOME_LABELS, Outcome

OUTCOME_COLORS = {Outcome.APPROVED: "green", Outcome.NEEDS_REVIEW: "orange", Outcome.ON_HOLD: "blue", Outcome.REJECTED: "red"}
OUTCOME_ICONS = {
    Outcome.APPROVED: ":material/check_circle:",
    Outcome.NEEDS_REVIEW: ":material/rate_review:",
    Outcome.ON_HOLD: ":material/pause_circle:",
    Outcome.REJECTED: ":material/block:",
}
# Tables can't show badges, so they use a coloured dot.
OUTCOME_DOTS = {Outcome.APPROVED: "🟢", Outcome.NEEDS_REVIEW: "🟠", Outcome.ON_HOLD: "🔵", Outcome.REJECTED: "🔴"}
OUTCOME_HEADLINES = {
    Outcome.APPROVED: "Ready to pay: every check passed.",
    Outcome.NEEDS_REVIEW: "A person needs to make a judgment call.",
    Outcome.ON_HOLD: "Waiting on someone outside AP before it can be paid.",
    Outcome.REJECTED: "Do not pay.",
}


def render_outcome_badge(outcome: Outcome) -> None:
    st.badge(OUTCOME_LABELS[outcome], icon=OUTCOME_ICONS[outcome], color=OUTCOME_COLORS[outcome])
