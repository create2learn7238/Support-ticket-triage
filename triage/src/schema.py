# src/schema.py - Pydantic models for tickets, model outputs, and triage decisions.

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

VALID_CATEGORIES: set[str] = {
    "billing",
    "account_access",
    "technical_issue",
    "shipping_delivery",
    "security_fraud",
    "legal_privacy",
    "product_question",
    "sales_partnership",
    "feedback",
    "other",
}

VALID_PRIORITIES: set[str] = {"low", "medium", "high", "urgent"}


class ReviewReason(str, Enum):
    EMPTY_OR_SHORT = "EMPTY_OR_SHORT"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    LLM_FAILED = "LLM_FAILED"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    RULE_CONFLICT = "RULE_CONFLICT"
    URGENT_LOW_CONFIDENCE = "URGENT_LOW_CONFIDENCE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


class Ticket(BaseModel):
    """Normalized ticket record loaded from dataset."""
    id: str
    received_at: str = ""
    customer: str = ""
    subject: str = ""
    body: str = ""
    text: str = ""
    original_length: int = 0
    was_truncated: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def populate_text(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("text"):
                subj = data.get("subject", "")
                body = data.get("body", "")
                data["text"] = f"{subj}\n\n{body}".strip()
        return data


class ModelOutput(BaseModel):
    """Structured LLM output."""
    category: str
    priority: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str = Field(..., max_length=200)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        norm = v.strip().lower()
        if norm not in VALID_CATEGORIES:
            raise ValueError(f"Unknown category '{v}'. Expected one of {sorted(VALID_CATEGORIES)}")
        return norm

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        norm = v.strip().lower()
        if norm not in VALID_PRIORITIES:
            raise ValueError(f"Unknown priority '{v}'. Expected one of {sorted(VALID_PRIORITIES)}")
        return norm

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, v: str) -> str:
        return v.strip()


class Decision(BaseModel):
    """Final triage decision for a ticket."""
    ticket_id: str
    status: str
    category: Optional[str] = None
    priority: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    review_reason: Optional[ReviewReason] = None
    model_used: str
    attempts: int = Field(default=1, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    prompt_version: str
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"auto_handled", "human_review"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}, got '{v}'")
        return v

    @field_validator("category")
    @classmethod
    def validate_category_opt(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        norm = v.strip().lower()
        if norm not in VALID_CATEGORIES:
            raise ValueError(f"Unknown category '{v}'")
        return norm

    @field_validator("priority")
    @classmethod
    def validate_priority_opt(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        norm = v.strip().lower()
        if norm not in VALID_PRIORITIES:
            raise ValueError(f"Unknown priority '{v}'")
        return norm

    @model_validator(mode="after")
    def validate_review_state(self) -> "Decision":
        if self.status == "human_review" and self.review_reason is None:
            raise ValueError("human_review requires review_reason")
        if self.status == "auto_handled" and self.review_reason is not None:
            raise ValueError("auto_handled cannot have review_reason")
        return self
