"""The single SQLite file that holds reference data, the ledger, runs and saved readings."""
import sqlite3
from pathlib import Path

from invoice_engine.config import DATABASE_PATH

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
IN_MEMORY_DATABASE = ":memory:"


def open_database_connection(database_path: Path | str = DATABASE_PATH) -> sqlite3.Connection:
    """Opens the database and creates any missing tables. Pass IN_MEMORY_DATABASE for a throwaway one."""
    if database_path != IN_MEMORY_DATABASE:
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    # Streamlit runs each session in its own thread; all writes go through `with connection:` transactions.
    connection = sqlite3.connect(database_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return connection
