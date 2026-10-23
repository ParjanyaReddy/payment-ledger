"""Integration Tests for Append-Only Ledger Immutability Trigger.

Proves that PostgreSQL engine-level triggers reject all UPDATE and DELETE
operations on the ledger_entries table with an explicit error.
"""

from decimal import Decimal

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.ledger_entry import LedgerEntry
from app.models.transaction import Transaction


@pytest.mark.asyncio
async def test_ledger_entry_update_prevented_by_trigger(db_session: AsyncSession) -> None:
    """Verify PostgreSQL trigger rejects UPDATE on ledger_entries."""
    # 1. Create balanced accounts, transaction, and entries
    acc_a = Account(currency="USD", balance=Decimal("100.00"), initial_balance=Decimal("100.00"))
    acc_b = Account(currency="USD", balance=Decimal("0.00"), initial_balance=Decimal("0.00"))
    db_session.add_all([acc_a, acc_b])
    await db_session.flush()

    txn = Transaction(
        from_account_id=acc_a.id,
        to_account_id=acc_b.id,
        amount=Decimal("40.00"),
        status="COMPLETED",
    )
    db_session.add(txn)
    await db_session.flush()

    debit_entry = LedgerEntry(
        transaction_id=txn.id,
        account_id=acc_a.id,
        amount=Decimal("40.00"),
        direction="DEBIT",
    )
    credit_entry = LedgerEntry(
        transaction_id=txn.id,
        account_id=acc_b.id,
        amount=Decimal("40.00"),
        direction="CREDIT",
    )
    acc_a.balance -= Decimal("40.00")
    acc_b.balance += Decimal("40.00")
    db_session.add_all([debit_entry, credit_entry])
    await db_session.commit()

    # 2. Attempt direct SQL UPDATE on the ledger entry
    stmt = (
        update(LedgerEntry).where(LedgerEntry.id == debit_entry.id).values(amount=Decimal("999.00"))
    )
    with pytest.raises(DBAPIError) as exc_info:
        await db_session.execute(stmt)
        await db_session.commit()

    assert "ledger_entries is append-only" in str(exc_info.value)
    await db_session.rollback()


@pytest.mark.asyncio
async def test_ledger_entry_delete_prevented_by_trigger(db_session: AsyncSession) -> None:
    """Verify PostgreSQL trigger rejects DELETE on ledger_entries."""
    # 1. Create balanced accounts, transaction, and entries
    acc_a = Account(currency="USD", balance=Decimal("100.00"), initial_balance=Decimal("100.00"))
    acc_b = Account(currency="USD", balance=Decimal("0.00"), initial_balance=Decimal("0.00"))
    db_session.add_all([acc_a, acc_b])
    await db_session.flush()

    txn = Transaction(
        from_account_id=acc_a.id,
        to_account_id=acc_b.id,
        amount=Decimal("30.00"),
        status="COMPLETED",
    )
    db_session.add(txn)
    await db_session.flush()

    debit_entry = LedgerEntry(
        transaction_id=txn.id,
        account_id=acc_a.id,
        amount=Decimal("30.00"),
        direction="DEBIT",
    )
    credit_entry = LedgerEntry(
        transaction_id=txn.id,
        account_id=acc_b.id,
        amount=Decimal("30.00"),
        direction="CREDIT",
    )
    acc_a.balance -= Decimal("30.00")
    acc_b.balance += Decimal("30.00")
    db_session.add_all([debit_entry, credit_entry])
    await db_session.commit()

    # 2. Attempt direct SQL DELETE on the ledger entry
    stmt = delete(LedgerEntry).where(LedgerEntry.id == credit_entry.id)
    with pytest.raises(DBAPIError) as exc_info:
        await db_session.execute(stmt)
        await db_session.commit()

    assert "ledger_entries is append-only" in str(exc_info.value)
    await db_session.rollback()
