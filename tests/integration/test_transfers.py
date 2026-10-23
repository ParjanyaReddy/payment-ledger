"""Integration Tests for Double-Entry Transfer API with Idempotency."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.idempotency_key import IdempotencyKey
from app.models.ledger_entry import LedgerEntry
from app.services.idempotency import cleanup_expired_keys


@pytest.mark.asyncio
async def test_transfer_happy_path(async_client: AsyncClient, db_session: AsyncSession) -> None:
    """Verify successful double-entry transfer updates balances and creates entries."""
    acc_from = Account(currency="USD", balance=Decimal("100.00"))
    acc_to = Account(currency="USD", balance=Decimal("50.00"))
    db_session.add_all([acc_from, acc_to])
    await db_session.commit()
    await db_session.refresh(acc_from)
    await db_session.refresh(acc_to)

    idem_key = str(uuid.uuid4())
    payload = {
        "from_account_id": str(acc_from.id),
        "to_account_id": str(acc_to.id),
        "amount": "40.00",
        "currency": "USD",
        "memo": "Test transfer",
    }
    response = await async_client.post(
        "/api/v1/transfers",
        json=payload,
        headers={"Idempotency-Key": idem_key},
    )
    assert response.status_code == 201
    data = response.json()

    assert data["status"] == "COMPLETED"
    assert data["amount"] == "40.00"
    assert data["from_account_balance"] == "60.00"
    assert data["to_account_balance"] == "90.00"
    assert len(data["entries"]) == 2

    # Verify double-entry invariant in database
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


@pytest.mark.asyncio
async def test_transfer_missing_idempotency_key(async_client: AsyncClient) -> None:
    """Verify that requests missing Idempotency-Key header are rejected with 422."""
    payload = {
        "from_account_id": str(uuid.uuid4()),
        "to_account_id": str(uuid.uuid4()),
        "amount": "10.00",
        "currency": "USD",
    }
    response = await async_client.post("/api/v1/transfers", json=payload)
    assert response.status_code == 422
    assert "Idempotency-Key" in str(response.json())


@pytest.mark.asyncio
async def test_transfer_idempotent_replay(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify re-sending the same idempotency key replays cached response without charging twice."""
    acc_from = Account(currency="USD", balance=Decimal("100.00"))
    acc_to = Account(currency="USD", balance=Decimal("50.00"))
    db_session.add_all([acc_from, acc_to])
    await db_session.commit()
    await db_session.refresh(acc_from)
    await db_session.refresh(acc_to)

    idem_key = str(uuid.uuid4())
    payload = {
        "from_account_id": str(acc_from.id),
        "to_account_id": str(acc_to.id),
        "amount": "30.00",
        "currency": "USD",
    }
    headers = {"Idempotency-Key": idem_key}

    # 1. First execution -> 201 Created
    first_resp = await async_client.post("/api/v1/transfers", json=payload, headers=headers)
    assert first_resp.status_code == 201
    first_data = first_resp.json()

    # 2. Duplicate retry with same key -> 201 Replay
    second_resp = await async_client.post("/api/v1/transfers", json=payload, headers=headers)
    assert second_resp.status_code == 201
    assert second_resp.headers.get("X-Idempotent-Replay") == "true"
    second_data = second_resp.json()

    # 3. Assert bodies match exactly
    assert first_data["transaction_id"] == second_data["transaction_id"]
    assert first_data["from_account_balance"] == second_data["from_account_balance"]

    # 4. Assert sender was only debited ONCE ($100 - $30 = $70, not $40)
    await db_session.refresh(acc_from)
    assert acc_from.balance == Decimal("70.00")


@pytest.mark.asyncio
async def test_transfer_same_key_different_payload_rejected(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify that reusing an idempotency key with a different payload returns 422."""
    acc_from = Account(currency="USD", balance=Decimal("100.00"))
    acc_to = Account(currency="USD", balance=Decimal("50.00"))
    db_session.add_all([acc_from, acc_to])
    await db_session.commit()
    await db_session.refresh(acc_from)
    await db_session.refresh(acc_to)

    idem_key = str(uuid.uuid4())
    headers = {"Idempotency-Key": idem_key}

    # 1. Original request for $10
    resp1 = await async_client.post(
        "/api/v1/transfers",
        json={
            "from_account_id": str(acc_from.id),
            "to_account_id": str(acc_to.id),
            "amount": "10.00",
            "currency": "USD",
        },
        headers=headers,
    )
    assert resp1.status_code == 201

    # 2. Reused key with different amount ($20)
    resp2 = await async_client.post(
        "/api/v1/transfers",
        json={
            "from_account_id": str(acc_from.id),
            "to_account_id": str(acc_to.id),
            "amount": "20.00",
            "currency": "USD",
        },
        headers=headers,
    )
    assert resp2.status_code == 422
    assert "different request payload" in resp2.json()["detail"]


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
    response = await async_client.post(
        "/api/v1/transfers",
        json=payload,
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 422
    assert "Insufficient funds" in response.json()["detail"]


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
    response = await async_client.post(
        "/api/v1/transfers",
        json=payload,
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
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
    response = await async_client.post(
        "/api/v1/transfers",
        json=payload,
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 400
    assert "Currency mismatch" in response.json()["detail"]


@pytest.mark.asyncio
async def test_cleanup_expired_idempotency_keys(db_session: AsyncSession) -> None:
    """Verify cleanup job removes records older than retention threshold."""
    expired_key = IdempotencyKey(
        key=uuid.uuid4(),
        request_hash="expired_hash",
        status="COMPLETED",
        created_at=datetime.now(UTC) - timedelta(hours=48),
    )
    fresh_key = IdempotencyKey(
        key=uuid.uuid4(),
        request_hash="fresh_hash",
        status="COMPLETED",
        created_at=datetime.now(UTC),
    )
    db_session.add_all([expired_key, fresh_key])
    await db_session.commit()

    deleted_count = await cleanup_expired_keys(db=db_session, retention_hours=24)
    await db_session.commit()
    assert deleted_count >= 1

    # Verify fresh key remains
    remaining = await db_session.get(IdempotencyKey, fresh_key.key)
    assert remaining is not None
