"""Pydantic Boundary Schemas for Account Operations.

Enforces string-based decimal representation for monetary values to guarantee
zero precision loss across HTTP JSON serialization.
"""

import re
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AccountCreate(BaseModel):
    """Request payload for creating a new account."""

    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Three-letter ISO currency code (e.g. USD, EUR, GBP)",
        examples=["USD"],
    )
    initial_balance: str = Field(
        default="0.00",
        description="Initial balance formatted as an exact decimal string",
        examples=["1000.00"],
    )

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        """Ensure currency code is uppercase letters."""
        v = v.strip().upper()
        if not re.match(r"^[A-Z]{3}$", v):
            raise ValueError("Currency must be a valid 3-letter ISO code (e.g., USD, EUR)")
        return v

    @field_validator("initial_balance")
    @classmethod
    def validate_initial_balance(cls, v: str) -> str:
        """Validate that initial balance is a non-negative decimal string with at most 2 decimal places."""
        v = v.strip()
        try:
            dec = Decimal(v)
        except InvalidOperation as err:
            raise ValueError(f"Invalid monetary decimal string: '{v}'") from err

        if dec < Decimal("0.00"):
            raise ValueError("Initial balance cannot be negative")

        if not dec.is_finite():
            raise ValueError("Monetary amount must be a finite number")

        # Verify scale does not exceed 2 decimal places
        exp = dec.as_tuple().exponent
        if not isinstance(exp, int) or exp < -2:
            raise ValueError("Monetary amount cannot have more than 2 decimal places")

        return f"{dec:.2f}"


class AccountResponse(BaseModel):
    """Response payload for account entity."""

    id: uuid.UUID
    currency: str
    balance: str
    holds: str = "0.00"
    available_balance: str = "0.00"
    version: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("balance", "holds", "available_balance", mode="before")
    @classmethod
    def format_decimal_fields(cls, v: object) -> str:
        """Format Decimal values to exact 2-decimal string representation."""
        if isinstance(v, Decimal):
            return f"{v:.2f}"
        if isinstance(v, (int, float, str)):
            return f"{Decimal(str(v)):.2f}"
        return str(v)
