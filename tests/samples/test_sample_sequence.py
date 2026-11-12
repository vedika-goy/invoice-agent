"""The samples end to end: every row of expected.csv, and the ground-truth quotes against the real PDFs."""
import pytest

from invoice_engine.config import SAMPLE_INVOICES_FOLDER
from invoice_engine.database.connection import IN_MEMORY_DATABASE, open_database_connection
from invoice_engine.decision.types import ReasonCode
from invoice_engine.numbers_check.service import build_invoice_facts, check_reading_and_numbers
from invoice_engine.reading.repository import SavedReadingRepository
from invoice_engine.reading.service import InvoiceReadingService
from invoice_engine.self_test.service import load_self_test_steps, run_self_test
from invoice_engine.utils.pdf_document import extract_pdf_text, has_text_layer
from invoice_engine.utils.sample_invoices import build_expected_reading, load_sample_specs
from tests.factories import TEST_TODAY

SPECS = load_sample_specs()


def test_every_expected_result_matches(ground_truth_reader):
    reading_service = InvoiceReadingService(ground_truth_reader,
                                            SavedReadingRepository(open_database_connection(IN_MEMORY_DATABASE)))
    results = run_self_test(reading_service, load_self_test_steps(), today_provider=lambda: TEST_TODAY)
    mismatches = [f"step {r.step.step_number} {r.step.target}: expected {r.step.expected_outcome} "
                  f"{r.step.expected_reason_codes}, got {r.actual_outcome} {r.actual_reason_codes}"
                  for r in results if not r.is_match]
    assert mismatches == []


@pytest.mark.parametrize("document", [d for d in SPECS["documents"] if not d["is_scan"]], ids=lambda d: d["file_name"])
def test_every_ground_truth_quote_is_printed_in_its_pdf(document):
    pdf_bytes = (SAMPLE_INVOICES_FOLDER / document["file_name"]).read_bytes()
    reading = build_expected_reading(document, SPECS["vendors"])
    step = check_reading_and_numbers(reading, build_invoice_facts(reading), extract_pdf_text(pdf_bytes), TEST_TODAY)
    assert ReasonCode.QUOTE_NOT_IN_DOCUMENT not in {finding.code for finding in step.findings}


@pytest.mark.parametrize("document", SPECS["documents"], ids=lambda d: d["file_name"])
def test_scanned_samples_have_no_text_layer(document):
    pdf_bytes = (SAMPLE_INVOICES_FOLDER / document["file_name"]).read_bytes()
    assert has_text_layer(pdf_bytes) is not document["is_scan"]
