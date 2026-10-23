"""Integration Tests Proving Database-Level Constraints.

Verifies that PostgreSQL database-level CHECK constraints physically reject
corrupted or invalid records even if an application bypass were attempted.
"""

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.ledger_entry import LedgerEntry
from app.models.transaction import Transaction


@pytest.mark.asyncio
async def test_db_constraint_account_negative_balance(db_session: AsyncSession) -> None:
    """Verify PostgreSQL rejects negative balance (CHECK balance >= 0)."""
    bad_account = Account(
        currency="USD",
        balance=Decimal("-10.00"),  # Violates check_account_balance_non_negative
    )
    db_session.add(bad_account)
    with pytest.raises(IntegrityError, match="check_account_balance_non_negative"):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_db_constraint_transaction_amount_must_be_positive(
    db_session: AsyncSession,
) -> None:
    """Verify PostgreSQL rejects non-positive transaction amounts (CHECK amount > 0)."""
    # Create a valid destination account first
    valid_account = Account(currency="USD", balance=Decimal("100.00"))
    db_session.add(valid_account)
    await db_session.commit()
    await db_session.refresh(valid_account)

    bad_txn = Transaction(
        to_account_id=valid_account.id,
        amount=Decimal("0.00"),  # Violates check_transaction_amount_positive
        status="PENDING",
    )
    db_session.add(bad_txn)
    with pytest.raises(IntegrityError, match="check_transaction_amount_positive"):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_db_constraint_transaction_status_valid(db_session: AsyncSession) -> None:
    """Verify PostgreSQL rejects invalid transaction status."""
    valid_account = Account(currency="USD", balance=Decimal("50.00"))
    db_session.add(valid_account)
    await db_session.commit()
    await db_session.refresh(valid_account)

    bad_txn = Transaction(
        to_account_id=valid_account.id,
        amount=Decimal("25.00"),
        status="INVALID_STATUS",  # Violates check_transaction_status_valid
    )
    db_session.add(bad_txn)
    with pytest.raises(IntegrityError, match="check_transaction_status_valid"):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_db_constraint_ledger_entry_direction_valid(db_session: AsyncSession) -> None:
    """Verify PostgreSQL rejects invalid ledger entry direction."""
    acc = Account(currency="USD", balance=Decimal("50.00"))
    db_session.add(acc)
    await db_session.commit()
    await db_session.refresh(acc)

    txn = Transaction(
        to_account_id=acc.id,
        amount=Decimal("10.00"),
        status="COMPLETED",
    )
    db_session.add(txn)
    await db_session.commit()
    await db_session.refresh(txn)

    bad_entry = LedgerEntry(
        transaction_id=txn.id,
        account_id=acc.id,
        direction="SIDEWAYS",  # Violates check_ledger_entry_direction_valid
        amount=Decimal("10.00"),
    )
    db_session.add(bad_entry)
    with pytest.raises(IntegrityError, match="check_ledger_entry_direction_valid"):
        await db_session.commit()
    await db_session.rollback()
