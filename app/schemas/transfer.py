"""Pydantic Boundary Schemas for Transfer Operations.

Validates transfer requests and serializes double-entry transfer responses
using string-based decimal precision.
"""

import re
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TransferRequest(BaseModel):
    """Payload for executing a transfer between two accounts."""

    from_account_id: uuid.UUID = Field(
        ...,
        description="Source account UUID to debit",
    )
    to_account_id: uuid.UUID = Field(
        ...,
        description="Destination account UUID to credit",
    )
    amount: str = Field(
        ...,
        description="Transfer amount formatted as an exact decimal string (e.g. '100.50')",
        examples=["50.00"],
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
        description="Optional memo or description for the transfer",
        examples=["Lunch split"],
    )

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        """Ensure currency is 3 uppercase alphabetic characters."""
        v = v.strip().upper()
        if not re.match(r"^[A-Z]{3}$", v):
            raise ValueError("Currency must be a valid 3-letter ISO code (e.g., USD, EUR)")
        return v

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: str) -> str:
        """Validate that amount is a strictly positive decimal with at most 2 decimal places."""
        v = v.strip()
        try:
            dec = Decimal(v)
        except InvalidOperation as err:
            raise ValueError(f"Invalid monetary decimal string: '{v}'") from err

        if not dec.is_finite():
            raise ValueError("Monetary amount must be a finite number")

        if dec <= Decimal("0.00"):
            raise ValueError("Transfer amount must be strictly greater than zero")

        exp = dec.as_tuple().exponent
        if not isinstance(exp, int) or exp < -2:
            raise ValueError("Monetary amount cannot have more than 2 decimal places")

        return f"{dec:.2f}"


class LedgerEntryResponse(BaseModel):
    """Schema representing one side of a double-entry pair."""

    id: uuid.UUID
    account_id: uuid.UUID
    direction: str
    amount: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("amount", mode="before")
    @classmethod
    def format_amount(cls, v: object) -> str:
        """Format Decimal amount to exact 2-decimal string representation."""
        if isinstance(v, Decimal):
            return f"{v:.2f}"
        return str(v)


class TransferResponse(BaseModel):
    """Response returned upon successful atomic transfer execution."""

    transaction_id: uuid.UUID
    status: str
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: str
    currency: str
    memo: str | None
    from_account_balance: str
    to_account_balance: str
    entries: list[LedgerEntryResponse]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
