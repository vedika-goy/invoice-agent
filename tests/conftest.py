import sqlite3

import pytest

from invoice_engine.database.connection import IN_MEMORY_DATABASE, open_database_connection
from invoice_engine.demo_data.service import reset_demo_data
from invoice_engine.pipeline.service import InvoicePipelineService
from invoice_engine.reading.repository import SavedReadingRepository
from invoice_engine.reading.service import InvoiceReadingService
from samples.ground_truth import GroundTruthReadingClient
from tests.factories import TEST_TODAY


@pytest.fixture
def demo_connection() -> sqlite3.Connection:
    connection = open_database_connection(IN_MEMORY_DATABASE)
    reset_demo_data(connection)
    yield connection
    connection.close()


@pytest.fixture(scope="session")
def ground_truth_reader() -> GroundTruthReadingClient:
    return GroundTruthReadingClient()


@pytest.fixture
def pipeline(demo_connection: sqlite3.Connection, ground_truth_reader: GroundTruthReadingClient) -> InvoicePipelineService:
    reading_service = InvoiceReadingService(ground_truth_reader, SavedReadingRepository(demo_connection))
    return InvoicePipelineService(demo_connection, reading_service, lambda: TEST_TODAY)
