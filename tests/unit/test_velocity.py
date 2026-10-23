"""Unit Tests for Velocity Fraud Detection Rules."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.transaction import Transaction
from app.services.exceptions import VelocityLimitExceededError
from app.services.velocity import check_velocity_limits


@pytest.mark.asyncio
async def test_velocity_frequency_limit_triggers(db_session: AsyncSession) -> None:
    """Verify that exceeding max transactions within the rolling window raises VelocityLimitExceededError."""
    # Create two accounts
    acc_id = uuid.uuid4()
    merchant_id = uuid.uuid4()
    acc = Account(
        id=acc_id, currency="USD", balance=Decimal("5000.00"), initial_balance=Decimal("5000.00")
    )
    merchant = Account(
        id=merchant_id, currency="USD", balance=Decimal("0.00"), initial_balance=Decimal("0.00")
    )
    db_session.add_all([acc, merchant])
    await db_session.flush()

    # Insert 5 recent transactions from acc_id (default window limit is 5)
    now = datetime.now(UTC)
    for _ in range(5):
        txn = Transaction(
            id=uuid.uuid4(),
            from_account_id=acc_id,
            to_account_id=merchant_id,
            amount=Decimal("10.00"),
            status="COMPLETED",
            created_at=now,
        )
        db_session.add(txn)
    await db_session.flush()

    # 6th activity should be rejected
    with pytest.raises(VelocityLimitExceededError) as exc:
        await check_velocity_limits(
            db=db_session,
            account_id=acc_id,
            requested_amount=Decimal("10.00"),
        )
    assert "Transaction frequency limit exceeded" in str(exc.value)


@pytest.mark.asyncio
async def test_velocity_daily_volume_limit_triggers(db_session: AsyncSession) -> None:
    """Verify that exceeding cumulative daily volume limit raises VelocityLimitExceededError."""
    acc_id = uuid.uuid4()
    merchant_id = uuid.uuid4()
    acc = Account(
        id=acc_id, currency="USD", balance=Decimal("20000.00"), initial_balance=Decimal("20000.00")
    )
    merchant = Account(
        id=merchant_id, currency="USD", balance=Decimal("0.00"), initial_balance=Decimal("0.00")
    )
    db_session.add_all([acc, merchant])
    await db_session.flush()

    # Insert a single large transaction of $9,500.00 today (default limit is $10,000.00)
    txn = Transaction(
        id=uuid.uuid4(),
        from_account_id=acc_id,
        to_account_id=merchant_id,
        amount=Decimal("9500.00"),
        status="COMPLETED",
        created_at=datetime.now(UTC),
    )
    db_session.add(txn)
    await db_session.flush()

    # Additional $600.00 puts total at $10,100.00 > $10,000.00 -> should raise
    with pytest.raises(VelocityLimitExceededError) as exc:
        await check_velocity_limits(
            db=db_session,
            account_id=acc_id,
            requested_amount=Decimal("600.00"),
        )
    assert "Daily transaction volume limit exceeded" in str(exc.value)


@pytest.mark.asyncio
async def test_velocity_under_limits_passes(db_session: AsyncSession) -> None:
    """Verify that requests within frequency and volume boundaries pass cleanly."""
    acc_id = uuid.uuid4()
    acc = Account(
        id=acc_id, currency="USD", balance=Decimal("1000.00"), initial_balance=Decimal("1000.00")
    )
    db_session.add(acc)
    await db_session.flush()

    # Should not raise any exception
    await check_velocity_limits(
        db=db_session,
        account_id=acc_id,
        requested_amount=Decimal("100.00"),
    )
