"""Intake: check the uploaded file and fingerprint it before anything else runs."""
import hashlib
import logging

from invoice_engine.intake.schemas import IntakeResult
from invoice_engine.pipeline.schemas import StepResult
from invoice_engine.policy.config import MAX_PAGE_COUNT, MAX_UPLOAD_SIZE_BYTES
from invoice_engine.utils.pdf_document import count_pdf_pages, has_text_layer

logger = logging.getLogger(__name__)

INTAKE_STEP_NUMBER = 0
INTAKE_STEP_TITLE = "Receive the file"
PDF_SIGNATURE = b"%PDF-"
# Some PDF writers put a few bytes before the signature; readers accept it within the first 1 KB.
PDF_SIGNATURE_SEARCH_BYTES = 1024
BYTES_PER_MEGABYTE = 1024 * 1024


def build_file_fingerprint(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


def check_uploaded_file(pdf_bytes: bytes) -> IntakeResult:
    size_bytes = len(pdf_bytes)
    if size_bytes == 0:
        return _build_refusal("The file is empty.", size_bytes)
    if size_bytes > MAX_UPLOAD_SIZE_BYTES:
        size_megabytes = size_bytes / BYTES_PER_MEGABYTE
        limit_megabytes = MAX_UPLOAD_SIZE_BYTES // BYTES_PER_MEGABYTE
        return _build_refusal(f"The file is {size_megabytes:.1f} MB; the limit is {limit_megabytes} MB.", size_bytes)
    if PDF_SIGNATURE not in pdf_bytes[:PDF_SIGNATURE_SEARCH_BYTES]:
        return _build_refusal("The file is not a PDF.", size_bytes)
    try:
        page_count = count_pdf_pages(pdf_bytes)
    except RuntimeError as error:
        logger.warning("Uploaded PDF could not be opened (%d bytes): %s", size_bytes, error)
        return _build_refusal("The PDF is damaged and can't be opened.", size_bytes)
    if page_count == 0 or page_count > MAX_PAGE_COUNT:
        return _build_refusal(f"The PDF has {page_count} pages; 1 to {MAX_PAGE_COUNT} are accepted.", size_bytes)
    return IntakeResult(
        is_valid=True,
        problem=None,
        fingerprint=build_file_fingerprint(pdf_bytes),
        size_bytes=size_bytes,
        page_count=page_count,
        has_text_layer=has_text_layer(pdf_bytes),
    )


def build_intake_step(intake: IntakeResult, file_name: str, earlier_run_id: int | None) -> StepResult:
    if not intake.is_valid:
        return StepResult.from_findings(INTAKE_STEP_NUMBER, INTAKE_STEP_TITLE, [f"Refused: {intake.problem}"], [])
    kind = "text PDF" if intake.has_text_layer else "scanned PDF (no text layer)"
    details = [
        f"{file_name}: {kind}, {intake.page_count} page(s), {intake.size_bytes / 1024:.0f} KB.",
        f"Fingerprint (SHA-256): {intake.fingerprint[:12]}…",
    ]
    if earlier_run_id is None:
        details.append("New file: no earlier run has this fingerprint.")
    else:
        details.append(f"Already seen: run {earlier_run_id} has this exact file, so it opens instead of a new decision.")
    return StepResult.from_findings(INTAKE_STEP_NUMBER, INTAKE_STEP_TITLE, details, [])


def _build_refusal(problem: str, size_bytes: int) -> IntakeResult:
    return IntakeResult(
        is_valid=False, problem=problem, fingerprint=None, size_bytes=size_bytes, page_count=0, has_text_layer=False
    )
