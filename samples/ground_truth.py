"""A stand-in for the Claude reader that returns each sample's known reading, for tests and offline runs."""
from pathlib import Path

from invoice_engine.config import SAMPLE_INVOICES_FOLDER, SAMPLE_SPECS_PATH
from invoice_engine.intake.service import build_file_fingerprint
from invoice_engine.reading.schemas import InvoiceReading
from invoice_engine.reading.types import ReadingUnavailableError
from invoice_engine.utils.sample_invoices import build_expected_reading, load_sample_specs


class GroundTruthReadingClient:
    model_id = "ground truth (offline, no AI)"

    def __init__(self, specs_path: Path = SAMPLE_SPECS_PATH, invoices_folder: Path = SAMPLE_INVOICES_FOLDER) -> None:
        specs = load_sample_specs(specs_path)
        self._readings_by_fingerprint: dict[str, InvoiceReading] = {}
        for document in specs["documents"]:
            pdf_path = invoices_folder / document["file_name"]
            if pdf_path.is_file():
                fingerprint = build_file_fingerprint(pdf_path.read_bytes())
                self._readings_by_fingerprint[fingerprint] = build_expected_reading(document, specs["vendors"])

    def read_invoice(self, pdf_bytes: bytes) -> InvoiceReading:
        reading = self._readings_by_fingerprint.get(build_file_fingerprint(pdf_bytes))
        if reading is None:
            raise ReadingUnavailableError("offline mode only knows the sample invoices")
        return reading
