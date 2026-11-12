"""Step 1: read the invoice, reusing a saved reading when the same file was read before."""
import logging
from datetime import datetime, timezone

from invoice_engine.decision.service import build_finding
from invoice_engine.decision.types import ReasonCode
from invoice_engine.pipeline.schemas import StepResult
from invoice_engine.reading.config import MAX_READING_ATTEMPTS
from invoice_engine.reading.repository import SavedReadingRepository
from invoice_engine.reading.schemas import InvoiceReading, ReadingReport, ReadingResult
from invoice_engine.reading.types import InvoiceReader, ReadingResponseInvalidError, ReadingUnavailableError
from invoice_engine.utils.money import format_money, to_money
from invoice_engine.utils.text_matching import keep_alphanumeric

logger = logging.getLogger(__name__)

READ_STEP_NUMBER = 1
READ_STEP_TITLE = "Read the invoice"
SCAN_READ_COUNT = 2


class InvoiceReadingService:
    def __init__(self, invoice_reader: InvoiceReader, saved_reading_repository: SavedReadingRepository) -> None:
        self._invoice_reader = invoice_reader
        self._saved_reading_repository = saved_reading_repository

    def read(self, pdf_bytes: bytes, fingerprint: str, is_scan: bool) -> ReadingResult:
        """Scans are read twice and compared; readings that worked are saved by fingerprint, failures are not."""
        saved_result = self._saved_reading_repository.get_saved_reading(fingerprint)
        if saved_result is not None:
            return ReadingResult(reading=saved_result.reading,
                                 report=saved_result.report.model_copy(update={"was_reused": True}))
        read_count = SCAN_READ_COUNT if is_scan else 1
        readings: list[InvoiceReading] = []
        total_attempt_count = 0
        for _ in range(read_count):
            reading, attempt_count, failure = self._read_with_one_retry(pdf_bytes)
            total_attempt_count += attempt_count
            if reading is None:
                report = self._build_report(is_scan, read_count, total_attempt_count, [], failure)
                return ReadingResult(reading=None, report=report)
            readings.append(reading)
        disagreements = find_reading_differences(readings[0], readings[1]) if is_scan else []
        report = self._build_report(is_scan, read_count, total_attempt_count, disagreements, None)
        self._saved_reading_repository.save_reading(fingerprint, readings[0], report)
        return ReadingResult(reading=readings[0], report=report)

    def _read_with_one_retry(self, pdf_bytes: bytes) -> tuple[InvoiceReading | None, int, str | None]:
        failure = None
        for attempt_number in range(1, MAX_READING_ATTEMPTS + 1):
            try:
                return self._invoice_reader.read_invoice(pdf_bytes), attempt_number, None
            except ReadingResponseInvalidError as error:
                failure = str(error)
                logger.warning("Reading attempt %d of %d was invalid: %s", attempt_number, MAX_READING_ATTEMPTS, error)
            except ReadingUnavailableError as error:
                # The SDK has already retried transient errors; retrying here would only add waiting.
                return None, attempt_number, str(error)
        return None, MAX_READING_ATTEMPTS, failure

    def _build_report(self, is_scan: bool, read_count: int, attempt_count: int, disagreements: list[str],
                      failure: str | None) -> ReadingReport:
        return ReadingReport(
            model_id=self._invoice_reader.model_id,
            is_scan=is_scan,
            read_count=read_count,
            attempt_count=attempt_count,
            disagreements=disagreements,
            failure=failure,
            was_reused=False,
            read_at=datetime.now(timezone.utc),
        )


def find_reading_differences(first: InvoiceReading, second: InvoiceReading) -> list[str]:
    """Labels of the values two readings of the same scan disagree on. Descriptions and quotes are ignored."""
    differences = []
    first_values = _list_comparable_values(first)
    second_values = dict(_list_comparable_values(second))
    for label, first_value in first_values:
        if second_values.get(label, "<missing>") != first_value:
            differences.append(label)
    if len(first.line_items) != len(second.line_items):
        differences.append("number of lines")
    return differences


def build_read_step(result: ReadingResult) -> StepResult:
    title = READ_STEP_TITLE
    report = result.report
    if result.reading is None:
        finding = build_finding(ReasonCode.READING_FAILED, problem=report.failure or "unknown error")
        details = [f"{report.model_id} couldn't read the document after {report.attempt_count} call(s)."]
        return StepResult.from_findings(READ_STEP_NUMBER, title, details, [finding])
    if report.was_reused:
        details = [f"Reused the reading saved on {report.read_at:%Y-%m-%d %H:%M} UTC for this exact file (no AI call)."]
    else:
        details = [f"Read by {report.model_id} in {report.attempt_count} call(s)."]
    findings = []
    if report.is_scan and report.disagreements:
        findings.append(build_finding(ReasonCode.SCAN_READINGS_DISAGREE, field_list=", ".join(report.disagreements)))
    elif report.is_scan:
        details.append("Scanned, so it was read twice: both readings agree on every value.")
    details.append(_build_reading_summary(result.reading))
    return StepResult.from_findings(READ_STEP_NUMBER, title, details, findings)


def _list_comparable_values(reading: InvoiceReading) -> list[tuple[str, str]]:
    values = [
        ("document type", reading.document_type.value),
        ("number of invoices", str(reading.invoice_count_in_file)),
        ("currency", reading.currency_code or ""),
        ("prices include tax", str(reading.prices_include_tax)),
    ]
    for label, read_text in [("vendor name", reading.vendor_name), ("tax ID", reading.vendor_tax_id),
                             ("invoice number", reading.invoice_number), ("PO number", reading.po_number),
                             ("bank account", reading.bank_account_number)]:
        values.append((label, keep_alphanumeric(read_text.value or "")))
    for label, read_date in [("invoice date", reading.invoice_date), ("due date", reading.due_date)]:
        values.append((label, read_date.value.isoformat() if read_date.value else ""))
    for label, read_amount in [("subtotal", reading.subtotal), ("tax", reading.tax), ("shipping", reading.shipping),
                               ("discount", reading.discount), ("total", reading.total)]:
        values.append((label, str(to_money(read_amount.value)) if read_amount.value is not None else ""))
    for line_number, line in enumerate(reading.line_items, start=1):
        values.append((f"line {line_number} quantity", str(line.quantity)))
        values.append((f"line {line_number} unit price", str(to_money(line.unit_price))))
        values.append((f"line {line_number} amount", str(to_money(line.line_amount))))
    return values


def _build_reading_summary(reading: InvoiceReading) -> str:
    parts = [reading.document_type.value.replace("_", " ")]
    if reading.vendor_name.value:
        parts.append(f"from {reading.vendor_name.value}")
    if reading.invoice_number.value:
        parts.append(f"number {reading.invoice_number.value}")
    parts.append(f"{len(reading.line_items)} line(s)")
    if reading.total.value is not None:
        parts.append(f"total {format_money(to_money(reading.total.value), reading.currency_code)}")
    return "Read: " + ", ".join(parts) + "."
