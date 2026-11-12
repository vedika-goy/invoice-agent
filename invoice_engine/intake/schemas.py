from pydantic import BaseModel


class IntakeResult(BaseModel):
    is_valid: bool
    problem: str | None
    fingerprint: str | None  # SHA-256 of the file bytes
    size_bytes: int
    page_count: int
    has_text_layer: bool
