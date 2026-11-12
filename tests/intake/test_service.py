import hashlib

from invoice_engine.config import SAMPLE_INVOICES_FOLDER
from invoice_engine.intake.service import check_uploaded_file
from invoice_engine.policy.config import MAX_UPLOAD_SIZE_BYTES

SAMPLE_PDF_BYTES = (SAMPLE_INVOICES_FOLDER / "happy_summit_packaging.pdf").read_bytes()


def test_valid_pdf_is_fingerprinted_with_sha256():
    result = check_uploaded_file(SAMPLE_PDF_BYTES)
    assert result.is_valid
    assert result.fingerprint == hashlib.sha256(SAMPLE_PDF_BYTES).hexdigest()


def test_files_that_are_not_usable_pdfs_are_refused_with_a_reason():
    assert check_uploaded_file(b"").problem == "The file is empty."
    assert check_uploaded_file(b"hello, not a pdf").problem == "The file is not a PDF."
    assert check_uploaded_file(b"%PDF-1.7 truncated garbage").problem == "The PDF is damaged and can't be opened."
    assert "limit is 10 MB" in check_uploaded_file(b"%PDF-" + b"0" * MAX_UPLOAD_SIZE_BYTES).problem
