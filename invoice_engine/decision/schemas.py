from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from invoice_engine.decision.types import Outcome, Owner, ReasonCode


class Finding(BaseModel):
    """One reason behind a decision, with the numbers that triggered it."""

    code: ReasonCode
    outcome: Outcome | None  # None for notes
    owner: Owner | None
    owner_name: str | None  # a named person, e.g. the PO requester
    title: str
    explanation: str
    unblock_action: str | None
    measured: str | None  # e.g. "+3.4%"
    limit: str | None  # e.g. "2%"
    details: dict[str, str]  # the values the templates were filled with


class Decision(BaseModel):
    outcome: Outcome
    findings: list[Finding]  # most serious first, notes last
    owners: list[str]
    policy_version: str
    total: Decimal | None
    currency_code: str | None
    due_date: date | None
    suggested_po_number: str | None
    vendor_email_draft: str | None
