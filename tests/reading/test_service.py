from invoice_engine.database.connection import IN_MEMORY_DATABASE, open_database_connection
from invoice_engine.decision.types import ReasonCode
from invoice_engine.reading.repository import SavedReadingRepository
from invoice_engine.reading.schemas import InvoiceReading, ReadAmount
from invoice_engine.reading.service import InvoiceReadingService, build_read_step
from invoice_engine.reading.types import ReadingResponseInvalidError, ReadingUnavailableError
from invoice_engine.utils.sample_invoices import build_expected_reading, load_sample_specs

SPECS = load_sample_specs()
SAMPLE_READING = build_expected_reading(SPECS["documents"][0], SPECS["vendors"])


class ScriptedReader:
    """Plays back a list of answers: an InvoiceReading, or an exception to raise."""

    model_id = "scripted"

    def __init__(self, answers: list) -> None:
        self.answers = list(answers)
        self.call_count = 0

    def read_invoice(self, pdf_bytes: bytes) -> InvoiceReading:
        self.call_count += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _service(reader: ScriptedReader) -> InvoiceReadingService:
    return InvoiceReadingService(reader, SavedReadingRepository(open_database_connection(IN_MEMORY_DATABASE)))


def test_saved_reading_is_reused_without_calling_the_ai_again():
    reader = ScriptedReader([SAMPLE_READING])
    service = _service(reader)
    service.read(b"pdf", "fingerprint-1", is_scan=False)
    second = service.read(b"pdf", "fingerprint-1", is_scan=False)
    assert (reader.call_count, second.report.was_reused, second.reading) == (1, True, SAMPLE_READING)


def test_an_answer_that_does_not_fit_the_schema_is_retried_once():
    reader = ScriptedReader([ReadingResponseInvalidError("bad"), SAMPLE_READING])
    result = _service(reader).read(b"pdf", "fingerprint-2", is_scan=False)
    assert (result.reading, result.report.attempt_count) == (SAMPLE_READING, 2)


def test_two_bad_answers_go_to_review_and_are_not_saved():
    reader = ScriptedReader([ReadingResponseInvalidError("bad"), ReadingResponseInvalidError("bad"), SAMPLE_READING])
    service = _service(reader)
    failed = service.read(b"pdf", "fingerprint-3", is_scan=False)
    assert failed.reading is None
    assert [f.code for f in build_read_step(failed).findings] == [ReasonCode.READING_FAILED]
    assert service.read(b"pdf", "fingerprint-3", is_scan=False).reading == SAMPLE_READING


def test_service_outage_fails_fast_because_the_sdk_already_retried():
    reader = ScriptedReader([ReadingUnavailableError("down"), SAMPLE_READING])
    result = _service(reader).read(b"pdf", "fingerprint-4", is_scan=False)
    assert (result.reading, reader.call_count) == (None, 1)


def test_scans_are_read_twice_and_disagreements_flagged():
    misread = SAMPLE_READING.model_copy(update={"total": ReadAmount(value=1.0, quote="$1.00")})
    reader = ScriptedReader([SAMPLE_READING, misread])
    result = _service(reader).read(b"pdf", "fingerprint-5", is_scan=True)
    assert (reader.call_count, result.report.disagreements) == (2, ["total"])
    assert [f.code for f in build_read_step(result).findings] == [ReasonCode.SCAN_READINGS_DISAGREE]
