"""Unit Tests for Transfer Request and Response Schemas."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.transfer import TransferRequest


def test_transfer_request_valid() -> None:
    """Verify valid transfer request parsing and normalization."""
    from_id = uuid.uuid4()
    to_id = uuid.uuid4()
    payload = TransferRequest(
        from_account_id=from_id,
        to_account_id=to_id,
        amount="150.25",
        currency="usd",
        memo="Dinner reimbursement",
    )
    assert payload.from_account_id == from_id
    assert payload.to_account_id == to_id
    assert payload.amount == "150.25"
    assert payload.currency == "USD"
    assert payload.memo == "Dinner reimbursement"


def test_transfer_request_zero_amount() -> None:
    """Verify zero amount is rejected."""
    with pytest.raises(ValidationError, match="Transfer amount must be strictly greater than zero"):
        TransferRequest(
            from_account_id=uuid.uuid4(),
            to_account_id=uuid.uuid4(),
            amount="0.00",
            currency="USD",
        )


def test_transfer_request_negative_amount() -> None:
    """Verify negative amount is rejected."""
    with pytest.raises(ValidationError, match="Transfer amount must be strictly greater than zero"):
        TransferRequest(
            from_account_id=uuid.uuid4(),
            to_account_id=uuid.uuid4(),
            amount="-25.00",
            currency="USD",
        )


def test_transfer_request_too_many_decimal_places() -> None:
    """Verify amount with > 2 decimal places is rejected."""
    with pytest.raises(ValidationError, match="cannot have more than 2 decimal places"):
        TransferRequest(
            from_account_id=uuid.uuid4(),
            to_account_id=uuid.uuid4(),
            amount="10.123",
            currency="USD",
        )


def test_transfer_request_invalid_currency() -> None:
    """Verify invalid currency code is rejected."""
    with pytest.raises(ValidationError):
        TransferRequest(
            from_account_id=uuid.uuid4(),
            to_account_id=uuid.uuid4(),
            amount="10.00",
            currency="US",
        )
    with pytest.raises(ValidationError, match="Currency must be a valid 3-letter ISO code"):
        TransferRequest(
            from_account_id=uuid.uuid4(),
            to_account_id=uuid.uuid4(),
            amount="10.00",
            currency="US1",
        )
