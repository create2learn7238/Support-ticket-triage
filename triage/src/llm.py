# src/llm.py - Model abstractions (MockModel and RealModel) with retry support.

import asyncio
import json
import random
from pathlib import Path
from typing import Any, Protocol, Tuple

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

CATEGORY_KEYWORDS = {
    "billing": ["charge", "charged", "refund", "invoice", "receipt", "renewal", "promo", "discount", "card", "payment", "kartenzahlung"],
    "account_access": ["login", "log in", "password", "reset", "two-factor", "locked out", "delete my account", "close my account", "change email"],
    "technical_issue": ["crash", "sync", "lag", "slow", "offline", "export", "hub", "camera", "not working", "will not open"],
    "shipping_delivery": ["tracking", "delivery", "arrived", "wrong item", "damaged", "address", "ship"],
    "security_fraud": ["fraud", "unauthorised", "unauthorized", "not mine", "hacked", "breach", "betrug", "fraude", "frode", "धोखा", "不正"],
    "legal_privacy": ["legal", "breach of", "complaint", "data privacy", "my data", "lawsuit"],
    "sales_partnership": ["reseller", "business", "partnership"],
    "feedback": ["thanks", "great product", "suggestion", "idea", "would be nice"],
    "product_question": ["how do i", "how to", "is it possible"],
}


class ModelProtocol(Protocol):
    async def classify(self, text: str) -> str:
        ...


class MockModel:
    def __init__(self, config: dict[str, Any], seed: int | None = 42):
        self.config = config
        self.mock_cfg = config.get("mock", {})
        self.rng = random.Random(seed)

    async def classify(self, text: str) -> str:
        # Check simulation rates
        if self.mock_cfg.get("slow_response_rate", 0) > 0 and self.rng.random() < self.mock_cfg.get("slow_response_rate", 0):
            await asyncio.sleep(2.0)

        if self.mock_cfg.get("timeout_rate", 0) > 0 and self.rng.random() < self.mock_cfg.get("timeout_rate", 0):
            raise asyncio.TimeoutError("Simulated mock timeout")

        if self.mock_cfg.get("invalid_json_rate", 0) > 0 and self.rng.random() < self.mock_cfg.get("invalid_json_rate", 0):
            return "NOT_VALID_JSON_STRING"

        text_lower = text.lower()
        matched_categories = []
        for cat, kws in CATEGORY_KEYWORDS.items():
            if any(kw in text_lower for kw in kws):
                matched_categories.append(cat)

        if len(matched_categories) == 1:
            category = matched_categories[0]
            confidence = 0.90
        elif len(matched_categories) > 1:
            category = matched_categories[0]
            confidence = 0.60
        else:
            category = "other"
            confidence = 0.40

        # Inject simulated low confidence rate
        if self.mock_cfg.get("low_confidence_rate", 0) > 0 and self.rng.random() < self.mock_cfg.get("low_confidence_rate", 0):
            confidence = 0.30

        # Priority rules
        urgent_kws = ["whole office", "all devices", "all our", "fraud", "hacked", "breach", "kartenzahlung", "betrug", "धोखा", "不正"]
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
        self.prompt_template = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else "{ticket_text}"

    async def classify(self, text: str) -> str:
        prompt = self.prompt_template.replace("{ticket_text}", text)
        provider = self.model_cfg.get("provider")
        raise NotImplementedError(f"Provider {provider} requires official credentials and API client.")


def get_model(config: dict[str, Any], seed: int | None = 42) -> ModelProtocol:
    provider = config.get("model", {}).get("provider", "mock")
    if provider == "mock":
        return MockModel(config, seed=seed)
    return RealModel(config)


async def call_with_retry(
    model: ModelProtocol, text: str, config: dict[str, Any]
) -> Tuple[str, int]:
    """Execute model call with tenacity retries and timeout."""
    model_cfg = config.get("model", {})
    timeout = float(model_cfg.get("timeout_seconds", 20))
    max_retries = int(model_cfg.get("max_retries", 3))

    attempts = 0

    async def _call():
        nonlocal attempts
        attempts += 1
        return await asyncio.wait_for(model.classify(text), timeout=timeout)

    retryer = AsyncRetrying(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=2.0),
        retry=retry_if_exception_type((asyncio.TimeoutError, ConnectionError, OSError)),
        reraise=True,
    )

    async for attempt in retryer:
        with attempt:
            raw_json = await _call()
            return raw_json, attempts

    raise RuntimeError("Model call failed after all retries")
