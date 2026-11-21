# src/precheck.py - Rule-based precheck to catch empty, junk, and prompt injections before calling LLM.

import re
from typing import Any
from src.schema import ReviewReason, Ticket

JUNK_PATTERNS = {
    "test",
    "asdf",
    "asdf asdf test test 123",
    "help",
    "sent from my phone",
}


def precheck(ticket: Ticket, config: dict[str, Any]) -> ReviewReason | None:
    """Returns ReviewReason if ticket should bypass the LLM and go straight to human review."""
    text = ticket.text.strip()
    body = ticket.body.strip()

    # 1. Check for prompt injection first to protect the model
    injection_patterns = config.get("safety", {}).get("injection_patterns", [])
    text_lower = text.lower()
    for pattern in injection_patterns:
        if pattern.lower() in text_lower:
            return ReviewReason.PROMPT_INJECTION

    # 2. Check for empty or too short
    min_chars = int(config.get("thresholds", {}).get("min_chars", 10))
    if not text or len(text) < min_chars:
        return ReviewReason.EMPTY_OR_SHORT

    # 3. Check if text has no letters (only numbers/symbols)
    if not re.search(r"[a-zA-Z\u0080-\uffff]", text):
        return ReviewReason.EMPTY_OR_SHORT

    # 4. Check for known junk body content
    body_clean = re.sub(r"[^\w\s]", "", body.lower()).strip()
    if body.lower() in JUNK_PATTERNS or body_clean in JUNK_PATTERNS:
        return ReviewReason.EMPTY_OR_SHORT

    return None
