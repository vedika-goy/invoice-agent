from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from invoice_engine.decision.types import Outcome
from invoice_engine.pipeline.schemas import DecisionRecord


class ReviewerActionType(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class StoredRun(BaseModel):
    run_id: int
    fingerprint: str
    file_name: str
    pdf_bytes: bytes
    created_at: datetime


class RunListing(BaseModel):
    """A run without its PDF bytes, for lists."""

    run_id: int
    file_name: str
    created_at: datetime


class StoredDecision(BaseModel):
    decision_id: int
    run_id: int
    created_at: datetime
    record: DecisionRecord


class ReviewerAction(BaseModel):
    action_id: int
    run_id: int
    decision_id: int
    action: ReviewerActionType
    system_outcome: Outcome  # what the process recommended when the reviewer acted
    reviewer_note: str
    created_at: datetime
