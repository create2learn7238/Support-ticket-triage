# src/llm.py - Model abstractions (MockModel and RealModel) with retry support.

import asyncio
import json
import os
import random
from pathlib import Path
from typing import Any, Optional, Protocol, Tuple

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Strict evaluation precedence for categories
CATEGORY_CHECK_ORDER = [
    "security_fraud",
    "legal_privacy",
    "billing",
    "account_access",
    "shipping_delivery",
    "technical_issue",
    "sales_partnership",
    "feedback",
    "product_question",
]

CATEGORY_KEYWORDS = {
    "security_fraud": [
        "fraud", "unauthorised", "unauthorized", "not mine", "hacked", "breach",
        "kartenzahlung", "betrug", "fraude", "frode", "धोखा", "不正"
    ],
    "legal_privacy": [
        "legal", "breach of", "complaint", "data privacy", "my data", "lawsuit"
    ],
    "billing": [
        "charge", "charged", "refund", "invoice", "receipt", "renewal", "promo",
        "discount", "card", "payment"
    ],
    "account_access": [
        "login", "log in", "password", "reset", "two-factor", "locked out",
        "delete my account", "close my account", "change email"
    ],
    "shipping_delivery": [
        "tracking", "delivery", "arrived", "wrong item", "damaged", "address", "ship"
    ],
    "technical_issue": [
        "devices are down", "all our devices", "whole office", "offline",
        "service down", "down for our company", "crash", "sync", "lag", "slow",
        "export", "hub", "camera", "not working", "will not open"
    ],
    "sales_partnership": ["reseller", "partnership"],  # "business" handled specially
    "feedback": ["thanks", "great product", "suggestion", "idea", "would be nice"],
    "product_question": ["how do i", "how to", "is it possible"],
}


class ModelProtocol(Protocol):
    async def classify(self, text: str, ticket_id: Optional[str] = None, attempt: int = 1) -> str:
        ...


class MockModel:
    def __init__(self, config: dict[str, Any], seed: Optional[int] = 42):
        self.config = config
        self.mock_cfg = config.get("mock", {})
        self.seed = seed

    def _get_rng(self, ticket_id: Optional[str], attempt: int) -> random.Random:
        if self.seed is None:
            return random.Random()
        t_id = ticket_id or "default"
        return random.Random(f"{self.seed}_{t_id}_{attempt}")

    async def classify(self, text: str, ticket_id: Optional[str] = None, attempt: int = 1) -> str:
        rng = self._get_rng(ticket_id, attempt)

        # Simulation checks
        slow_rate = float(self.mock_cfg.get("slow_response_rate", 0))
        if slow_rate > 0 and rng.random() < slow_rate:
            await asyncio.sleep(2.0)

        timeout_rate = float(self.mock_cfg.get("timeout_rate", 0))
        if timeout_rate > 0 and rng.random() < timeout_rate:
            raise asyncio.TimeoutError("Simulated mock timeout")

        invalid_rate = float(self.mock_cfg.get("invalid_json_rate", 0))
        if invalid_rate > 0 and rng.random() < invalid_rate:
            return "NOT_VALID_JSON_STRING"

        text_lower = text.lower()

        # Check categories in strict order
        matched_categories = []
        for cat in CATEGORY_CHECK_ORDER:
            kws = CATEGORY_KEYWORDS.get(cat, [])
            if any(kw in text_lower for kw in kws):
                matched_categories.append(cat)

        # Special check for 'business': word 'business' alone must NOT put a ticket
        # in sales_partnership if technical or billing words are present
        if "business" in text_lower:
            has_tech_or_billing = any(
                kw in text_lower
                for kw in (CATEGORY_KEYWORDS["technical_issue"] + CATEGORY_KEYWORDS["billing"])
            )
            if not has_tech_or_billing and "sales_partnership" not in matched_categories:
                matched_categories.append("sales_partnership")

        if len(matched_categories) == 1:
            category = matched_categories[0]
            confidence = 0.90
        elif len(matched_categories) > 1:
            category = matched_categories[0]  # First strong match wins
            confidence = 0.60
        else:
            category = "other"
            confidence = 0.40

        # Inject simulated low confidence rate
        low_conf_rate = float(self.mock_cfg.get("low_confidence_rate", 0))
        if low_conf_rate > 0 and rng.random() < low_conf_rate:
            confidence = 0.30

        # Priority rules
        urgent_kws = [
            "whole office", "all devices", "all our", "fraud", "hacked", "breach",
            "kartenzahlung", "betrug", "धोखा", "不正", "service down", "down for our company"
        ]
        high_kws = ["cannot log in", "locked out", "will not start", "charged twice", "double charge"]

        if any(kw in text_lower for kw in urgent_kws):
            priority = "urgent"
        elif any(kw in text_lower for kw in high_kws):
            priority = "high"
        elif category in ("shipping_delivery", "technical_issue"):
            priority = "medium"
        else:
            priority = "low"

        reason = f"Classified based on keywords for {category} with {priority} priority."
        payload = {
            "category": category,
            "priority": priority,
            "confidence": round(confidence, 2),
            "reason": reason[:200],
        }
        return json.dumps(payload)


class RealModel:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.model_cfg = config.get("model", {})
        prompt_file = Path("prompts/triage_v1.txt")
        if not prompt_file.exists():
            triage_root = Path(__file__).resolve().parent.parent
            prompt_file = triage_root / "prompts" / "triage_v1.txt"
        self.prompt_template = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else "{ticket_text}"

    async def classify(self, text: str, ticket_id: Optional[str] = None, attempt: int = 1) -> str:
        provider = self.model_cfg.get("provider", "").lower()
        prompt = self.prompt_template.replace("{ticket_text}", text)
        timeout = float(self.model_cfg.get("timeout_seconds", 20))

        if provider == "anthropic":
            try:
                import anthropic
            except ImportError:
                raise RuntimeError(
                    "The 'anthropic' package is required for provider 'anthropic'. "
                    "Install it using: pip install anthropic"
                )

            key_env = self.model_cfg.get("api_key_env", "ANTHROPIC_API_KEY")
            api_key = os.getenv(key_env)
            if not api_key:
                raise ValueError(
                    f"Anthropic API key not found in environment variable '{key_env}'."
                )

            client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)
            model_name = self.model_cfg.get("name", "claude-3-5-sonnet-20241022")
            response = await client.messages.create(
                model=model_name,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text

        elif provider in ("openai", "gemini"):
            raise NotImplementedError(
                f"Provider '{provider}' integration is not implemented yet. "
                "Only 'mock' and 'anthropic' are supported."
            )
        else:
            raise ValueError(f"Unsupported model provider: '{provider}'")


def get_model(config: dict[str, Any], seed: Optional[int] = 42) -> ModelProtocol:
    provider = config.get("model", {}).get("provider", "mock")
    if provider == "mock":
        return MockModel(config, seed=seed)
    return RealModel(config)


async def call_with_retry(
    model: ModelProtocol, text: str, config: dict[str, Any], ticket_id: Optional[str] = None
) -> Tuple[str, int]:
    """Execute model call with tenacity retries, passing ticket_id and attempt number."""
    model_cfg = config.get("model", {})
    timeout = float(model_cfg.get("timeout_seconds", 20))
    max_retries = int(model_cfg.get("max_retries", 3))

    attempts = 0

    async def _call():
        nonlocal attempts
        attempts += 1
        return await asyncio.wait_for(
            model.classify(text, ticket_id=ticket_id, attempt=attempts),
            timeout=timeout,
        )

    retryer = AsyncRetrying(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=2.0),
        retry=retry_if_exception_type((asyncio.TimeoutError, ConnectionError, OSError)),
        reraise=True,
    )

    async for attempt_state in retryer:
        with attempt_state:
            raw_json = await _call()
            return raw_json, attempts

    raise RuntimeError("Model call failed after all retries")
