# src/triage.py - Orchestrates end-to-end triage decision for a single ticket.

import time
from typing import Any
from pydantic import ValidationError

from src.schema import Decision, ModelOutput, ReviewReason, Ticket
from src.precheck import precheck
from src.rules import urgent_hint
from src.llm import call_with_retry


async def triage_one(ticket: Ticket, model: Any, config: dict[str, Any]) -> Decision:
    """Triage one ticket following strict precedence order. Never raises an exception."""
    model_cfg = config.get("model", {})
    provider = model_cfg.get("provider", "mock")
    model_name = model_cfg.get("name", "")
    model_used = f"{provider}/{model_name}" if model_name else provider
    prompt_version = model_cfg.get("prompt_version", "v1")

    thresholds = config.get("thresholds", {})
    urgent_conf_thresh = float(thresholds.get("urgent_confidence", 0.85))
    normal_conf_thresh = float(thresholds.get("normal_confidence", 0.70))

    try:
        # a) Precheck: check empty, short, or prompt injection (costs 0 model calls)
        precheck_reason = precheck(ticket, config)
        if precheck_reason is not None:
            return Decision(
                ticket_id=ticket.id,
                status="human_review",
                category=None,
                priority=None,
                confidence=None,
                review_reason=precheck_reason,
                model_used=model_used,
                attempts=0,
                latency_ms=0,
                prompt_version=prompt_version,
                note=f"Filtered in precheck: {precheck_reason.value}",
            )

        # b) Call LLM with retry
        start_time = time.perf_counter()
        attempts = 0
        try:
            raw_json, attempts = await call_with_retry(model, ticket.text, config)
            latency_ms = int((time.perf_counter() - start_time) * 1000)
        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return Decision(
                ticket_id=ticket.id,
                status="human_review",
                category=None,
                priority=None,
                confidence=None,
                review_reason=ReviewReason.LLM_FAILED,
                model_used=model_used,
                attempts=max(1, attempts),
                latency_ms=latency_ms,
                prompt_version=prompt_version,
                note=f"LLM call failed: {str(e)}",
            )

        # c) Parse and validate JSON with ModelOutput
        try:
            output = ModelOutput.model_validate_json(raw_json)
        except (ValidationError, Exception) as e:
            return Decision(
                ticket_id=ticket.id,
                status="human_review",
                category=None,
                priority=None,
                confidence=None,
                review_reason=ReviewReason.INVALID_OUTPUT,
                model_used=model_used,
                attempts=attempts,
                latency_ms=latency_ms,
                prompt_version=prompt_version,
                note=f"Invalid output format: {str(e)[:100]}",
            )

        # d) Safety conflict: urgent keywords in text but model says low or medium
        is_urgent_text = urgent_hint(ticket, config)
        if is_urgent_text and output.priority in ("low", "medium"):
            return Decision(
                ticket_id=ticket.id,
                status="human_review",
                category=output.category,
                priority=output.priority,
                confidence=output.confidence,
                review_reason=ReviewReason.RULE_CONFLICT,
                model_used=model_used,
                attempts=attempts,
                latency_ms=latency_ms,
                prompt_version=prompt_version,
                note=output.reason,
            )

        # e) Strict threshold for high and urgent:
        # A wrong urgent call is the costly mistake (fraud, major outage),
        # so high/urgent requires higher confidence than normal.
        if output.priority in ("high", "urgent") and output.confidence < urgent_conf_thresh:
            return Decision(
                ticket_id=ticket.id,
                status="human_review",
                category=output.category,
                priority=output.priority,
                confidence=output.confidence,
                review_reason=ReviewReason.URGENT_LOW_CONFIDENCE,
                model_used=model_used,
                attempts=attempts,
                latency_ms=latency_ms,
                prompt_version=prompt_version,
                note=output.reason,
            )

        # f) Normal confidence check
        if output.confidence < normal_conf_thresh:
            return Decision(
                ticket_id=ticket.id,
                status="human_review",
                category=output.category,
                priority=output.priority,
                confidence=output.confidence,
                review_reason=ReviewReason.LOW_CONFIDENCE,
                model_used=model_used,
                attempts=attempts,
                latency_ms=latency_ms,
                prompt_version=prompt_version,
                note=output.reason,
            )

        # g) Auto-handled
        return Decision(
            ticket_id=ticket.id,
            status="auto_handled",
            category=output.category,
            priority=output.priority,
            confidence=output.confidence,
            review_reason=None,
            model_used=model_used,
            attempts=attempts,
            latency_ms=latency_ms,
            prompt_version=prompt_version,
            note=output.reason,
        )

    except Exception as exc:
        # Fallback guarantee: triage_one must NEVER raise
        return Decision(
            ticket_id=ticket.id,
            status="human_review",
            category=None,
            priority=None,
            confidence=None,
            review_reason=ReviewReason.LLM_FAILED,
            model_used=model_used,
            attempts=1,
            latency_ms=0,
            prompt_version=prompt_version,
            note=f"Unexpected triage failure: {str(exc)}",
        )
