"""Runs (one per unique file), every decision made on them, and reviewer actions: the audit trail."""
import sqlite3
from datetime import datetime, timezone

from invoice_engine.decision.types import Outcome
from invoice_engine.pipeline.schemas import DecisionRecord
from invoice_engine.run_history.schemas import (
    ReviewerAction,
    ReviewerActionType,
    RunListing,
    StoredDecision,
    StoredRun,
)

LATEST_DECISION_PER_RUN_SQL = (
    "SELECT * FROM decisions WHERE decision_id IN (SELECT MAX(decision_id) FROM decisions GROUP BY run_id)"
)


class RunHistoryRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def find_run_id_by_fingerprint(self, fingerprint: str) -> int | None:
        row = self._connection.execute("SELECT run_id FROM runs WHERE fingerprint = ?", (fingerprint,)).fetchone()
        return row["run_id"] if row else None

    def create_run(self, fingerprint: str, file_name: str, pdf_bytes: bytes) -> tuple[int, bool]:
        """Returns (run_id, was_created). If the same file arrived concurrently, returns the existing run."""
        with self._connection:
            cursor = self._connection.execute(
                "INSERT OR IGNORE INTO runs (fingerprint, file_name, pdf_bytes, created_at) VALUES (?, ?, ?, ?)",
                (fingerprint, file_name, pdf_bytes, _now_iso()),
            )
        if cursor.rowcount == 1:
            return cursor.lastrowid, True
        return self.find_run_id_by_fingerprint(fingerprint), False

    def get_run(self, run_id: int) -> StoredRun | None:
        row = self._connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return StoredRun.model_validate(dict(row)) if row else None

    def list_runs(self) -> list[RunListing]:
        rows = self._connection.execute("SELECT run_id, file_name, created_at FROM runs ORDER BY run_id").fetchall()
        return [RunListing.model_validate(dict(row)) for row in rows]

    def add_decision(self, run_id: int, record: DecisionRecord) -> int:
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO decisions (run_id, trigger, outcome, policy_version, decision_record_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, record.trigger.value, record.decision.outcome.value, record.decision.policy_version,
                 record.model_dump_json(), _now_iso()),
            )
        return cursor.lastrowid

    def get_latest_decision(self, run_id: int) -> StoredDecision | None:
        row = self._connection.execute(
            "SELECT * FROM decisions WHERE run_id = ? ORDER BY decision_id DESC LIMIT 1", (run_id,)
        ).fetchone()
        return _to_stored_decision(row) if row else None

    def list_decisions(self, run_id: int) -> list[StoredDecision]:
        rows = self._connection.execute(
            "SELECT * FROM decisions WHERE run_id = ? ORDER BY decision_id", (run_id,)
        ).fetchall()
        return [_to_stored_decision(row) for row in rows]

    def list_latest_decisions(self) -> list[StoredDecision]:
        rows = self._connection.execute(LATEST_DECISION_PER_RUN_SQL + " ORDER BY run_id").fetchall()
        return [_to_stored_decision(row) for row in rows]

    def add_reviewer_action(self, run_id: int, decision_id: int, action: ReviewerActionType,
                            system_outcome: Outcome, reviewer_note: str) -> ReviewerAction:
        created_at = _now_iso()
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO reviewer_actions (run_id, decision_id, action, system_outcome, reviewer_note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, decision_id, action.value, system_outcome.value, reviewer_note, created_at),
            )
        return ReviewerAction(action_id=cursor.lastrowid, run_id=run_id, decision_id=decision_id, action=action,
                              system_outcome=system_outcome, reviewer_note=reviewer_note, created_at=created_at)

    def list_reviewer_actions(self, run_id: int | None = None) -> list[ReviewerAction]:
        if run_id is None:
            rows = self._connection.execute("SELECT * FROM reviewer_actions ORDER BY action_id").fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM reviewer_actions WHERE run_id = ? ORDER BY action_id", (run_id,)
            ).fetchall()
        return [ReviewerAction.model_validate(dict(row)) for row in rows]

    def delete_all_runs(self) -> None:
        """Decisions and reviewer actions go with their runs (ON DELETE CASCADE)."""
        with self._connection:
            self._connection.execute("DELETE FROM runs")


def _to_stored_decision(row: sqlite3.Row) -> StoredDecision:
    return StoredDecision(
        decision_id=row["decision_id"],
        run_id=row["run_id"],
        created_at=row["created_at"],
        record=DecisionRecord.model_validate_json(row["decision_record_json"]),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
