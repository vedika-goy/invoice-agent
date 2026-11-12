from typing import Protocol

from invoice_engine.reading.schemas import InvoiceReading


class InvoiceReader(Protocol):
    """Turns a PDF into an InvoiceReading. InvoiceReadingClient calls Claude; tests use a fake."""

    @property
    def model_id(self) -> str: ...

    def read_invoice(self, pdf_bytes: bytes) -> InvoiceReading:
        """Raises ReadingUnavailableError or ReadingResponseInvalidError."""
        ...


class ReadingUnavailableError(Exception):
    """The AI service couldn't be reached, or refused the request."""


class ReadingResponseInvalidError(Exception):
    """The AI answered, but the answer doesn't fit InvoiceReading."""
