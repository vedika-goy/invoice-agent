"""One set of engine objects per server process, shared by every page and browser session."""
import os
import sqlite3
from dataclasses import dataclass

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from invoice_engine.database.connection import open_database_connection
from invoice_engine.demo_data.service import ensure_demo_data_loaded
from invoice_engine.ledger.repository import LedgerRepository
from invoice_engine.pipeline.service import InvoicePipelineService
from invoice_engine.reading.client import InvoiceReadingClient
from invoice_engine.reading.repository import SavedReadingRepository
from invoice_engine.reading.service import InvoiceReadingService
from invoice_engine.reference_data.repository import ReferenceDataRepository
from invoice_engine.run_history.repository import RunHistoryRepository

API_KEY_NAME = "ANTHROPIC_API_KEY"


@dataclass(frozen=True)
class EngineContext:
    connection: sqlite3.Connection
    pipeline: InvoicePipelineService
    reading_service: InvoiceReadingService
    run_history: RunHistoryRepository
    reference_data: ReferenceDataRepository
    ledger: LedgerRepository
    has_api_key: bool


@st.cache_resource
def get_engine_context() -> EngineContext:
    connection = open_database_connection()
    ensure_demo_data_loaded(connection)
    api_key = read_api_key()
    reading_service = InvoiceReadingService(InvoiceReadingClient(api_key=api_key), SavedReadingRepository(connection))
    return EngineContext(
        connection=connection,
        pipeline=InvoicePipelineService(connection, reading_service),
        reading_service=reading_service,
        run_history=RunHistoryRepository(connection),
        reference_data=ReferenceDataRepository(connection),
        ledger=LedgerRepository(connection),
        has_api_key=api_key is not None,
    )


def read_api_key() -> str | None:
    """Streamlit secrets first (how Streamlit Cloud provides it), then the environment (.env loaded locally)."""
    try:
        secret_value = st.secrets.get(API_KEY_NAME)
    except StreamlitSecretNotFoundError:
        # No secrets.toml is the normal case for local runs; the environment is checked next.
        secret_value = None
    return secret_value or os.environ.get(API_KEY_NAME) or None
