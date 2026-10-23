"""Pydantic Boundary Schemas for Card Lifecycle Operations.

Enforces string-based decimal precision across card authorizations, holds,
captures, voids, and refunds.
"""

import re
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_decimal_string(v: str, field_name: str) -> str:
    """Validate that a string represents a strictly positive decimal with <= 2 decimal places."""
    v = v.strip()
    try:
        dec = Decimal(v)
    except InvalidOperation as err:
        raise ValueError(f"Invalid monetary decimal string: '{v}'") from err

    if dec <= Decimal("0.00"):
        raise ValueError(f"{field_name} must be strictly positive (got '{v}')")

    if not dec.is_finite():
        raise ValueError("Monetary amount must be a finite number")

    exp = dec.as_tuple().exponent
    if not isinstance(exp, int) or exp < -2:
        raise ValueError("Monetary amount cannot have more than 2 decimal places")

    return f"{dec:.2f}"


class CardAuthRequest(BaseModel):
    """Request payload for placing a card authorization hold."""

    account_id: uuid.UUID = Field(
        ...,
        description="Customer account UUID whose funds will be placed on hold",
    )
    merchant_id: uuid.UUID = Field(
        ...,
        description="Merchant account UUID that will receive settled funds upon capture",
    )
    amount: str = Field(
        ...,
        description="Hold amount as an exact positive decimal string (e.g. '150.00')",
        examples=["150.00"],
    )
    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Three-letter ISO currency code",
        examples=["USD"],
    )
    memo: str | None = Field(
        default=None,
        max_length=255,
        description="Optional memo or merchant descriptor",
        examples=["Dinner at Bistro"],
    )
    hold_duration_hours: int = Field(
        default=168,
        ge=1,
        le=720,
        description="Duration in hours before the authorization hold expires (1 to 720 hours)",
    )

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        """Validate currency code is 3 uppercase ASCII letters."""
        v = v.strip().upper()
        if not re.match(r"^[A-Z]{3}$", v):
            raise ValueError("Currency must be a valid 3-letter ISO code (e.g., USD, EUR)")
        return v

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: str) -> str:
        """Validate amount is a strictly positive decimal string with <= 2 decimal places."""
        return _validate_decimal_string(v, "Authorization amount")


class CardCaptureRequest(BaseModel):
    """Request payload for capturing an authorized card hold."""

    amount: str | None = Field(
        default=None,
        description="Optional capture amount. If omitted, captures the full authorized amount.",
        examples=["150.00"],
    )

    @field_validator("amount")
    @classmethod
    def validate_capture_amount(cls, v: str | None) -> str | None:
        """Validate optional capture amount."""
        if v is None:
            return None
        return _validate_decimal_string(v, "Capture amount")


class CardVoidRequest(BaseModel):
    """Request payload for voiding an active authorization hold."""

    reason: str | None = Field(
        default=None,
        max_length=255,
        description="Optional reason for voiding the authorization",
        examples=["Customer cancelled order"],
    )


class CardRefundRequest(BaseModel):
    """Request payload for refunding a captured transaction."""

    amount: str | None = Field(
        default=None,
        description="Optional refund amount. If omitted, refunds the full captured amount.",
        examples=["50.00"],
    )
    reason: str | None = Field(
        default=None,
        max_length=255,
        description="Optional reason for refunding the transaction",
        examples=["Returned damaged goods"],
    )

    @field_validator("amount")
    @classmethod
    def validate_refund_amount(cls, v: str | None) -> str | None:
        """Validate optional refund amount."""
        if v is None:
            return None
        return _validate_decimal_string(v, "Refund amount")


class CardAuthResponse(BaseModel):
    """Response payload for card lifecycle operations."""

    id: uuid.UUID
    account_id: uuid.UUID
    merchant_id: uuid.UUID
    amount: str
    captured_amount: str | None = None
    refunded_amount: str = "0.00"
    currency: str
    status: str
    memo: str | None = None
    transaction_id: uuid.UUID | None = None
    refund_transaction_id: uuid.UUID | None = None
    created_at: datetime
    expires_at: datetime
    captured_at: datetime | None = None
    voided_at: datetime | None = None
    message: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("amount", "captured_amount", "refunded_amount", mode="before")
    @classmethod
    def format_decimal_amounts(cls, v: object) -> str | None:
        """Format Decimal values to exact 2-decimal string representation."""
        if v is None:
            return None
        if isinstance(v, Decimal):
            return f"{v:.2f}"
        if isinstance(v, (int, float, str)):
            return f"{Decimal(str(v)):.2f}"
        return str(v)
