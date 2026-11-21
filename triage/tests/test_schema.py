# tests/test_schema.py – unit tests for src/schema.py.
#
# WHY THESE TESTS
# Schema validation is the first line of defence against bad LLM output and
# bad CSV rows.  These tests confirm that good data is accepted and that bad
# data raises a clear ValidationError – so we never silently pass garbage
# through the pipeline.
#
# HOW TO RUN
#   cd triage
#   pytest tests/test_schema.py -v

import sys
import os

# Allow imports from src/ without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from pydantic import ValidationError

from schema import (
    Decision,
    ModelOutput,
    ReviewReason,
    Ticket,
)


# ---------------------------------------------------------------------------
# Test 1 – Ticket accepts a normal row from the CSV
# ---------------------------------------------------------------------------

def test_ticket_valid():
    t = Ticket(
        id="T-0001",
        text="My order arrived with the wrong plug. Can you help?",
        meta={"subject": "Wrong item received", "customer": "Emma"},
    )
    assert t.id == "T-0001"
    assert "Emma" in t.meta["customer"]


# ---------------------------------------------------------------------------
# Test 2 – ModelOutput accepts a good LLM response and normalises case
# ---------------------------------------------------------------------------

def test_model_output_valid():
    out = ModelOutput(
        category="billing",
        priority="high",
        confidence=0.92,
        reason="Customer reports a double charge on their account.",
    )
    assert out.category == "billing"
    assert out.priority == "high"
    assert 0.0 <= out.confidence <= 1.0


def test_model_output_case_normalised():
    """LLM might return 'Billing' or 'BILLING'; validator should normalise it."""
    out = ModelOutput(
        category="  Billing  ",   # leading/trailing space + mixed case
        priority="HIGH",
        confidence=0.80,
        reason="Billing issue.",
    )
    assert out.category == "billing"
    assert out.priority == "high"


# ---------------------------------------------------------------------------
# Test 3 – ModelOutput rejects an unknown category
# ---------------------------------------------------------------------------

def test_model_output_bad_category():
    with pytest.raises(ValidationError) as exc_info:
        ModelOutput(
            category="refunds",   # not in VALID_CATEGORIES
            priority="low",
            confidence=0.75,
            reason="Some reason.",
        )
    # Check the error message mentions the bad value
    assert "refunds" in str(exc_info.value).lower() or "category" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Test 4 – ModelOutput rejects confidence outside [0, 1]
# ---------------------------------------------------------------------------

def test_model_output_bad_confidence():
    with pytest.raises(ValidationError):
        ModelOutput(
            category="billing",
            priority="medium",
            confidence=1.5,          # over 1.0 – not allowed
            reason="Some reason.",
        )

    with pytest.raises(ValidationError):
        ModelOutput(
            category="billing",
            priority="medium",
            confidence=-0.1,         # below 0.0 – not allowed
            reason="Some reason.",
        )


# ---------------------------------------------------------------------------
# Test 5 – Decision: auto_handled must not have a review_reason
# ---------------------------------------------------------------------------

def test_decision_auto_handled_valid():
    d = Decision(
        ticket_id="T-0010",
        status="auto_handled",
        category="technical_issue",
        priority="medium",
        confidence=0.88,
        review_reason=None,          # must be None for auto_handled
        model_used="mock/v1",
        latency_ms=312,
        attempts=1,
        prompt_version="v1",
    )
    assert d.status == "auto_handled"
    assert d.review_reason is None


def test_decision_human_review_valid():
    d = Decision(
        ticket_id="T-0093",
        status="human_review",
        category=None,
        priority=None,
        confidence=None,
        review_reason=ReviewReason.EMPTY_OR_SHORT,
        model_used="mock/v1",
        latency_ms=0,
        attempts=0,
        prompt_version="v1",
    )
    assert d.status == "human_review"
    assert d.review_reason == ReviewReason.EMPTY_OR_SHORT


# ---------------------------------------------------------------------------
# Test 6 – Decision: human_review without a reason must fail
# ---------------------------------------------------------------------------

def test_decision_human_review_missing_reason():
    with pytest.raises(ValidationError) as exc_info:
        Decision(
            ticket_id="T-0005",
            status="human_review",
            category=None,
            priority=None,
            confidence=None,
            review_reason=None,     # missing – must raise
            model_used="mock/v1",
            latency_ms=0,
            attempts=1,
            prompt_version="v1",
        )
    assert "review_reason" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Test 7 – Decision: auto_handled with a review_reason must fail
# ---------------------------------------------------------------------------

def test_decision_auto_handled_with_reason_fails():
    with pytest.raises(ValidationError):
        Decision(
            ticket_id="T-0007",
            status="auto_handled",
            category="feedback",
            priority="low",
            confidence=0.95,
            review_reason=ReviewReason.LOW_CONFIDENCE,  # must be None
            model_used="mock/v1",
            latency_ms=200,
            attempts=1,
            prompt_version="v1",
        )


# ---------------------------------------------------------------------------
# Test 8 – ReviewReason enum covers all expected members
# ---------------------------------------------------------------------------

def test_review_reason_enum_members():
    expected = {
        "EMPTY_OR_SHORT",
        "PROMPT_INJECTION",
        "LLM_FAILED",
        "INVALID_OUTPUT",
        "LOW_CONFIDENCE",
        "URGENT_LOW_CONFIDENCE",
        "RULE_CONFLICT",
    }
    actual = {member.name for member in ReviewReason}
    assert actual == expected
