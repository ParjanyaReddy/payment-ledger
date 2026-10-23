"""Unit Tests for Account Pydantic Schemas."""

import pytest
from pydantic import ValidationError

from app.schemas.account import AccountCreate


def test_account_create_valid() -> None:
    """Verify valid account payload creation and normalization."""
    payload = AccountCreate(currency="usd", initial_balance="250.50")
    assert payload.currency == "USD"
    assert payload.initial_balance == "250.50"


def test_account_create_default_balance() -> None:
    """Verify default initial balance is zero formatted string."""
    payload = AccountCreate(currency="EUR")
    assert payload.initial_balance == "0.00"


def test_account_create_invalid_currency() -> None:
    """Verify invalid currency code raises ValidationError."""
    with pytest.raises(ValidationError, match="Currency must be a valid 3-letter ISO code"):
        AccountCreate(currency="US1", initial_balance="100.00")

    with pytest.raises(ValidationError):
        AccountCreate(currency="US", initial_balance="100.00")


def test_account_create_negative_balance() -> None:
    """Verify negative initial balance is rejected."""
    with pytest.raises(ValidationError, match="Initial balance cannot be negative"):
        AccountCreate(currency="USD", initial_balance="-50.00")


def test_account_create_too_many_decimal_places() -> None:
    """Verify monetary amounts with > 2 decimal places are rejected."""
    with pytest.raises(ValidationError, match="cannot have more than 2 decimal places"):
        AccountCreate(currency="USD", initial_balance="10.555")


def test_account_create_non_numeric_balance() -> None:
    """Verify non-numeric string is rejected."""
    with pytest.raises(ValidationError, match="Invalid monetary decimal string"):
        AccountCreate(currency="USD", initial_balance="not-a-number")
