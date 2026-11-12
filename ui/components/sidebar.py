import streamlit as st

from invoice_engine.demo_data.service import reset_demo_data
from invoice_engine.policy.config import POLICY_VERSION
from invoice_engine.reading.config import READING_MODEL_ID
from ui.context.engine_context import EngineContext
from ui.stores.process_page_state import set_current_run_id


def render_sidebar(context: EngineContext) -> None:
    with st.sidebar:
        st.markdown("### :material/receipt_long: Invoice agent")
        st.caption("AI reads the invoice. Plain rules make the decision.")
        if context.has_api_key:
            st.success(f"Claude connected ({READING_MODEL_ID})", icon=":material/smart_toy:")
        else:
            st.warning("No Anthropic API key: invoices read before still work; new files can't be read.",
                       icon=":material/key_off:")
        st.caption(f"Policy version {POLICY_VERSION}")
        st.divider()
        with st.popover("Reset demo data", icon=":material/restart_alt:", width="stretch"):
            st.markdown("Clears every run, decision and approval, and reloads the vendor, PO and ledger CSVs. "
                        "Saved readings are kept, so samples stay instant.")
            if st.button("Reset now", type="primary", width="stretch"):
                reset_demo_data(context.connection)
                set_current_run_id(None)
                st.toast("Demo data reset.", icon=":material/restart_alt:")
                st.rerun()
