"""Unit Tests for Card Lifecycle Schemas and State Transition Constraints."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.card import (
    CardAuthRequest,
    CardCaptureRequest,
    CardRefundRequest,
    CardVoidRequest,
)
from app.services.exceptions import (
    InvalidCardStateTransitionError,
    InvalidRefundAmountError,
)


def test_card_auth_request_valid() -> None:
    """Test valid CardAuthRequest creation and validation."""
    account_id = uuid.uuid4()
    merchant_id = uuid.uuid4()
    req = CardAuthRequest(
        account_id=account_id,
        merchant_id=merchant_id,
        amount="150.50",
        currency="usd",
        memo="Dinner at Bistro",
        hold_duration_hours=72,
    )
    assert req.amount == "150.50"
    assert req.currency == "USD"
    assert req.hold_duration_hours == 72


def test_card_auth_request_negative_amount_rejected() -> None:
    """Test that negative authorization amounts are rejected."""
    with pytest.raises(ValidationError) as exc:
        CardAuthRequest(
            account_id=uuid.uuid4(),
            merchant_id=uuid.uuid4(),
            amount="-50.00",
            currency="USD",
        )
    assert "Authorization amount must be strictly positive" in str(exc.value)


def test_card_auth_request_zero_amount_rejected() -> None:
    """Test that zero authorization amounts are rejected."""
    with pytest.raises(ValidationError) as exc:
        CardAuthRequest(
            account_id=uuid.uuid4(),
            merchant_id=uuid.uuid4(),
            amount="0.00",
            currency="USD",
        )
    assert "Authorization amount must be strictly positive" in str(exc.value)


def test_card_auth_request_too_many_decimals_rejected() -> None:
    """Test that amounts with more than 2 decimal places are rejected."""
    with pytest.raises(ValidationError) as exc:
        CardAuthRequest(
            account_id=uuid.uuid4(),
            merchant_id=uuid.uuid4(),
            amount="10.999",
            currency="USD",
        )
    assert "Monetary amount cannot have more than 2 decimal places" in str(exc.value)


def test_card_auth_request_invalid_currency_rejected() -> None:
    """Test that invalid currency codes are rejected."""
    with pytest.raises(ValidationError) as exc:
        CardAuthRequest(
            account_id=uuid.uuid4(),
            merchant_id=uuid.uuid4(),
            amount="50.00",
            currency="US1",
        )
    assert "Currency must be a valid 3-letter ISO code" in str(exc.value)


def test_card_capture_request_validation() -> None:
    """Test CardCaptureRequest valid and invalid inputs."""
    req_full = CardCaptureRequest()
    assert req_full.amount is None

    req_partial = CardCaptureRequest(amount="75.25")
    assert req_partial.amount == "75.25"

    with pytest.raises(ValidationError):
        CardCaptureRequest(amount="-10.00")

    with pytest.raises(ValidationError):
        CardCaptureRequest(amount="10.555")


def test_card_void_request_validation() -> None:
    """Test CardVoidRequest optional reason."""
    req = CardVoidRequest(reason="User request")
    assert req.reason == "User request"

    req_default = CardVoidRequest()
    assert req_default.reason is None


def test_card_refund_request_validation() -> None:
    """Test CardRefundRequest valid and invalid amounts."""
    req_full = CardRefundRequest()
    assert req_full.amount is None

    req_partial = CardRefundRequest(amount="25.00", reason="Item defective")
    assert req_partial.amount == "25.00"
    assert req_partial.reason == "Item defective"

    with pytest.raises(ValidationError):
        CardRefundRequest(amount="-5.00")


def test_card_state_transition_exceptions() -> None:
    """Verify that domain exceptions provide clear error descriptions."""
    err_transition = InvalidCardStateTransitionError(
        current_status="VOIDED",
        attempted_action="CAPTURE",
    )
    assert "Cannot execute 'CAPTURE' on authorization in 'VOIDED' status" in str(err_transition)

    err_refund = InvalidRefundAmountError(requested="120.00", max_allowed="100.00")
    assert "Refund amount '120.00' exceeds maximum eligible refund '100.00'" in str(err_refund)
