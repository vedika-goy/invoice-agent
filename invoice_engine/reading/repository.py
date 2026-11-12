"""Saved readings, keyed by file fingerprint, so a re-run never calls the AI again."""
import sqlite3
from datetime import datetime, timezone

from invoice_engine.reading.schemas import InvoiceReading, ReadingReport, ReadingResult


class SavedReadingRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_saved_reading(self, fingerprint: str) -> ReadingResult | None:
        row = self._connection.execute(
            "SELECT reading_json, reading_report_json FROM saved_readings WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        if row is None:
            return None
        return ReadingResult(
            reading=InvoiceReading.model_validate_json(row["reading_json"]),
            report=ReadingReport.model_validate_json(row["reading_report_json"]),
        )

    def save_reading(self, fingerprint: str, reading: InvoiceReading, report: ReadingReport) -> None:
        """Keeps the first saved reading for a fingerprint: the same file always gives the same reading."""
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO saved_readings (fingerprint, reading_json, reading_report_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (fingerprint, reading.model_dump_json(), report.model_dump_json(),
                 datetime.now(timezone.utc).isoformat()),
            )
