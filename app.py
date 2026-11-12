"""Streamlit entry point.

Local run, from this folder:  set -a && source .env && set +a && .venv/bin/streamlit run app.py
"""
import streamlit as st

from ui.components.sidebar import render_sidebar
from ui.context.engine_context import get_engine_context

st.set_page_config(page_title="Invoice agent", page_icon=":material/receipt_long:", layout="wide")

navigation = st.navigation([
    st.Page("ui/pages/process_invoice.py", title="Process an invoice", icon=":material/play_circle:", default=True),
    st.Page("ui/pages/dashboard.py", title="Dashboard", icon=":material/monitoring:"),
    st.Page("ui/pages/how_it_decides.py", title="How it decides", icon=":material/rule:"),
])
render_sidebar(get_engine_context())
navigation.run()
