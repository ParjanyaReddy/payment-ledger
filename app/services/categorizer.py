# CORE LOGIC: understand this file line by line.
"""AI Transaction Categorization Service.

Defines the protocol and implementations for categorizing payment memos using:
1. Google Gemini Generative AI SDK (gemini-2.5-flash) with structured outputs.
2. Rule-based deterministic keyword matching engine (for offline environments).
3. Test mocks for deterministic unit and integration test verification.

Enforces:
- Canonical category taxonomy.
- Exponential backoff retry with a maximum of 3 attempts.
- Graceful degradation: falls back to "Uncategorized" on network/API failure without
  ever crashing the worker or delaying payment settlement.
"""

import asyncio
import logging
import re
from typing import Protocol

from pydantic import BaseModel, Field

from app.config import get_settings

logger = logging.getLogger(__name__)

# Canonical payment categories
VALID_CATEGORIES: set[str] = {
    "Food & Dining",
    "Transportation",
    "Utilities",
    "Entertainment",
    "Payroll",
    "Shopping",
    "Health & Medical",
    "Transfer",
    "Uncategorized",
}


class CategorizationResult(BaseModel):
    """Structured Pydantic boundary schema for LLM categorization responses."""

    category: str = Field(
        ...,
        description="One of the canonical financial categories",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0",
    )


class TransactionCategorizer(Protocol):
    """Abstract protocol for transaction memo categorizers."""

    async def categorize(self, memo: str | None) -> str:
        """Categorize a transaction memo string into a canonical category name."""
        ...


class RuleBasedCategorizer:
    """High-speed deterministic keyword categorizer for offline environments."""

    RULES: list[tuple[re.Pattern[str], str]] = [
        # Food & Dining
        (
            re.compile(
                r"\b(coffee|starbucks|dinner|lunch|pizza|food|burger|restaurant|cafe|grocer|trader joe|"
                r"whole foods|doordash|uber eats|bakery|chipotle|sweetgreen|sandwich|salad|mcdonald|"
                r"panera|shake shack|grill|cappuccino|bagel)\b",
                re.IGNORECASE,
            ),
            "Food & Dining",
        ),
        # Transportation
        (
            re.compile(
                r"\b(uber\b(?! eats)|lyft|taxi|subway transit|mta subway|subway train|metro|transit|gas\b|"
                r"shell|chevron|parking|flight|airline|airlines|train|amtrak|toll|exxon|exxonmobil|diesel|fuel)\b",
                re.IGNORECASE,
            ),
            "Transportation",
        ),
        # Utilities
        (
            re.compile(
                r"\b(electric|water|utility|utilities|internet|wifi|comcast|verizon|at&t|phone bill|"
                r"power|sewer|spectrum|coned|con edison|t-mobile|trash|heating)\b",
                re.IGNORECASE,
            ),
            "Utilities",
        ),
        # Entertainment
        (
            re.compile(
                r"\b(netflix|spotify|hulu|disney|movie|theatre|theater|cinema|steam|playstation|xbox|"
                r"concert|ticket|tickets|game|nintendo|broadway)\b",
                re.IGNORECASE,
            ),
            "Entertainment",
        ),
        # Payroll
        (
            re.compile(
                r"\b(salary|payroll|wages|wage|bonus|stipend|direct deposit|employer|compensation|"
                r"incentive|consulting fee|overtime)\b",
                re.IGNORECASE,
            ),
            "Payroll",
        ),
        # Shopping
        (
            re.compile(
                r"\b(amazon|walmart|target|ebay|clothes|shoes|electronics|best buy|apple store|ikea|"
                r"mall|zara|nike|home depot|costco|sephora|nordstrom|retail|hardware)\b",
                re.IGNORECASE,
            ),
            "Shopping",
        ),
        # Health & Medical
        (
            re.compile(
                r"\b(pharmacy|walgreens|cvs|doctor|dental|dentist|hospital|clinic|prescription|"
                r"therapy|optometry|rehab|rite aid|copay|vitamins|checkup)\b",
                re.IGNORECASE,
            ),
            "Health & Medical",
        ),
        # Transfer
        (
            re.compile(
                r"\b(transfer|split|rent|reimbursement|venmo|zelle|cash app|p2p|settle|loan|repay|"
                r"friend|wire transfer|roomie|landlord)\b",
                re.IGNORECASE,
            ),
            "Transfer",
        ),
    ]

    async def categorize(self, memo: str | None) -> str:
        """Match memo against deterministic patterns with immediate fallback."""
        if not memo or not memo.strip():
            return "Uncategorized"

        clean_memo = memo.strip()
        for pattern, category in self.RULES:
            if pattern.search(clean_memo):
                return category

        return "Uncategorized"


class GeminiCategorizer:
    """Production AI categorizer using the Google GenAI SDK (Gemini 2.5 Flash)."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.gemini_model
        self.fallback = RuleBasedCategorizer()
        self._client = None

        if self.api_key:
            try:
                from google import genai

                self._client = genai.Client(api_key=self.api_key)
            except Exception as err:
                logger.warning(
                    "Failed to initialize Google GenAI client: %s. Using rule fallback.", err
                )

    async def categorize(self, memo: str | None) -> str:
        """Categorize transaction memo using Gemini with exponential backoff retry.

        If GEMINI_API_KEY is not configured or network calls fail, gracefully
        falls back to RuleBasedCategorizer and finally "Uncategorized".
        """
        if not memo or not memo.strip():
            return "Uncategorized"

        # If no client configured, use fast rule-based fallback
        if not self._client:
            return await self.fallback.categorize(memo)

        prompt = (
            f"You are a financial transaction classification engine. "
            f"Classify the following transaction memo into EXACTLY one of these categories:\n"
            f"- Food & Dining\n"
            f"- Transportation\n"
            f"- Utilities\n"
            f"- Entertainment\n"
            f"- Payroll\n"
            f"- Shopping\n"
            f"- Health & Medical\n"
            f"- Transfer\n"
            f"- Uncategorized\n\n"
            f'Transaction memo: "{memo.strip()}"\n'
            f"Return only the exact category name."
        )

        # Retry loop: up to 3 attempts with exponential backoff
        delays = [0.2, 0.5, 1.0]
        for attempt, delay in enumerate(delays, start=1):
            try:
                # Run synchronous GenAI call in a thread pool to avoid blocking the async event loop
                response = await asyncio.to_thread(
                    self._client.models.generate_content,
                    model=self.model,
                    contents=prompt,
                )
                raw_text = (response.text or "").strip()

                # Clean response and validate category
                for cat in VALID_CATEGORIES:
                    if cat.lower() in raw_text.lower():
                        return cat

                return "Uncategorized"
            except Exception as err:
                logger.warning(
                    "Gemini categorization attempt %d/3 failed for memo '%s': %s",
                    attempt,
                    memo,
                    err,
                )
                if attempt < len(delays):
                    await asyncio.sleep(delay)

        # Fallback to deterministic rules if LLM exhausts retries
        return await self.fallback.categorize(memo)


class FakeCategorizer:
    """Configurable categorizer for deterministic testing."""

    def __init__(
        self,
        canned_category: str = "Food & Dining",
        should_fail: bool = False,
    ) -> None:
        self.canned_category = canned_category
        self.should_fail = should_fail
        self.call_count = 0

    async def categorize(self, memo: str | None) -> str:
        self.call_count += 1
        if self.should_fail:
            raise RuntimeError("Fake LLM forced failure for resilience testing")
        if not memo or not memo.strip():
            return "Uncategorized"
        return self.canned_category


def get_default_categorizer() -> TransactionCategorizer:
    """Factory creating the primary categorizer based on environment configuration."""
    settings = get_settings()
    if settings.gemini_api_key:
        return GeminiCategorizer(api_key=settings.gemini_api_key)
    return RuleBasedCategorizer()
