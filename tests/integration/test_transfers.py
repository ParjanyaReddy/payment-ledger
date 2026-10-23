"""Integration Tests for Double-Entry Transfer API."""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.ledger_entry import LedgerEntry


@pytest.mark.asyncio
async def test_transfer_happy_path(async_client: AsyncClient, db_session: AsyncSession) -> None:
    """Verify successful double-entry transfer updates balances and creates entries."""
    # 1. Create source and destination accounts
    acc_from = Account(currency="USD", balance=Decimal("100.00"))
    acc_to = Account(currency="USD", balance=Decimal("50.00"))
    db_session.add_all([acc_from, acc_to])
    await db_session.commit()
    await db_session.refresh(acc_from)
    await db_session.refresh(acc_to)

    # 2. Execute transfer via API
    payload = {
        "from_account_id": str(acc_from.id),
        "to_account_id": str(acc_to.id),
        "amount": "40.00",
        "currency": "USD",
        "memo": "Test transfer",
    }
    response = await async_client.post("/api/v1/transfers", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert data["status"] == "COMPLETED"
    assert data["amount"] == "40.00"
    assert data["from_account_balance"] == "60.00"
    assert data["to_account_balance"] == "90.00"
    assert len(data["entries"]) == 2

    # 3. Verify double-entry invariant in database
    txn_id = uuid.UUID(data["transaction_id"])
    entries_query = await db_session.execute(
        select(LedgerEntry).where(LedgerEntry.transaction_id == txn_id)
    )
    entries = entries_query.scalars().all()
    assert len(entries) == 2

    debit_entry = next(e for e in entries if e.direction == "DEBIT")
    credit_entry = next(e for e in entries if e.direction == "CREDIT")

    assert debit_entry.account_id == acc_from.id
    assert debit_entry.amount == Decimal("40.00")
    assert credit_entry.account_id == acc_to.id
    assert credit_entry.amount == Decimal("40.00")

    # Invariant: debits equal credits; net movement = 0
    assert debit_entry.amount == credit_entry.amount


@pytest.mark.asyncio
async def test_transfer_insufficient_funds(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify that overdraft attempt is rejected with 422 and balances remain untouched."""
    acc_from = Account(currency="USD", balance=Decimal("20.00"))
    acc_to = Account(currency="USD", balance=Decimal("100.00"))
    db_session.add_all([acc_from, acc_to])
    await db_session.commit()
    await db_session.refresh(acc_from)
    await db_session.refresh(acc_to)

    payload = {
        "from_account_id": str(acc_from.id),
        "to_account_id": str(acc_to.id),
        "amount": "50.00",
        "currency": "USD",
    }
    response = await async_client.post("/api/v1/transfers", json=payload)
    assert response.status_code == 422
    assert "Insufficient funds" in response.json()["detail"]

    # Verify balances were not modified
    await db_session.refresh(acc_from)
    await db_session.refresh(acc_to)
    assert acc_from.balance == Decimal("20.00")
    assert acc_to.balance == Decimal("100.00")


@pytest.mark.asyncio
async def test_transfer_self_transfer_rejected(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify that transfer to the same account is rejected with 400."""
    acc = Account(currency="USD", balance=Decimal("100.00"))
    db_session.add(acc)
    await db_session.commit()
    await db_session.refresh(acc)

    payload = {
        "from_account_id": str(acc.id),
        "to_account_id": str(acc.id),
        "amount": "10.00",
        "currency": "USD",
    }
    response = await async_client.post("/api/v1/transfers", json=payload)
    assert response.status_code == 400
    assert "Cannot transfer funds to the same account" in response.json()["detail"]


@pytest.mark.asyncio
async def test_transfer_currency_mismatch(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify that transfers between accounts with different currencies are rejected."""
    acc_usd = Account(currency="USD", balance=Decimal("100.00"))
    acc_eur = Account(currency="EUR", balance=Decimal("100.00"))
    db_session.add_all([acc_usd, acc_eur])
    await db_session.commit()
    await db_session.refresh(acc_usd)
    await db_session.refresh(acc_eur)

    payload = {
        "from_account_id": str(acc_usd.id),
        "to_account_id": str(acc_eur.id),
        "amount": "10.00",
        "currency": "USD",
    }
    response = await async_client.post("/api/v1/transfers", json=payload)
    assert response.status_code == 400
    assert "Currency mismatch" in response.json()["detail"]


@pytest.mark.asyncio
async def test_transfer_nonexistent_account(async_client: AsyncClient) -> None:
    """Verify that unknown account UUID returns 404 Not Found."""
    payload = {
        "from_account_id": str(uuid.uuid4()),
        "to_account_id": str(uuid.uuid4()),
        "amount": "10.00",
        "currency": "USD",
    }
    response = await async_client.post("/api/v1/transfers", json=payload)
    assert response.status_code == 404
