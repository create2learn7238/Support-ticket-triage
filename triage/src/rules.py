# src/rules.py - Safety keywords check to flag tickets that describe urgent situations.

from typing import Any
from src.schema import Ticket

MULTILINGUAL_URGENT = ["kartenzahlung", "betrug", "fraude", "frode", "धोखा", "不正"]


def urgent_hint(ticket: Ticket, config: dict[str, Any]) -> bool:
    """Return True if ticket contains urgent safety keywords across multiple languages."""
    text_lower = ticket.text.lower()
    keywords = config.get("safety", {}).get("urgent_keywords", [])

    for kw in keywords:
        if str(kw).lower() in text_lower:
            return True

    for term in MULTILINGUAL_URGENT:
        if term.lower() in text_lower:
            return True

    return False
