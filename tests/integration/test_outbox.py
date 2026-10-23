"""Integration Tests for Transactional Outbox Pattern and Background Worker."""

import asyncio
import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.outbox import Outbox
from app.models.transaction import Transaction
from app.services.categorizer import FakeCategorizer, RuleBasedCategorizer
from app.workers.outbox_worker import process_outbox_batch
from tests.conftest import TestingSessionLocal


@pytest.mark.asyncio
async def test_transfer_creates_pending_outbox_record(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify executing a transfer atomically enqueues a PENDING outbox record."""
    acc_a = Account(currency="USD", balance=Decimal("100.00"), initial_balance=Decimal("100.00"))
    acc_b = Account(currency="USD", balance=Decimal("0.00"), initial_balance=Decimal("0.00"))
    db_session.add_all([acc_a, acc_b])
    await db_session.commit()
    await db_session.refresh(acc_a)
    await db_session.refresh(acc_b)

    idem_key = str(uuid.uuid4())
    payload = {
        "from_account_id": str(acc_a.id),
        "to_account_id": str(acc_b.id),
        "amount": "15.00",
        "currency": "USD",
        "memo": "Whole Foods groceries and snacks",
    }
    resp = await async_client.post(
        "/api/v1/transfers",
        json=payload,
        headers={"Idempotency-Key": idem_key},
    )
    assert resp.status_code == 201
    txn_id = uuid.UUID(resp.json()["transaction_id"])

    # Query outbox table for this transaction
    stmt = select(Outbox).where(Outbox.transaction_id == txn_id)
    outbox_entry = (await db_session.execute(stmt)).scalar_one_or_none()

    assert outbox_entry is not None
    assert outbox_entry.status == "PENDING"
    assert outbox_entry.attempts == 0


@pytest.mark.asyncio
async def test_process_outbox_batch_categorizes_transaction(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify outbox worker processes pending records and updates transaction AI category."""
    acc_a = Account(currency="USD", balance=Decimal("100.00"), initial_balance=Decimal("100.00"))
    acc_b = Account(currency="USD", balance=Decimal("0.00"), initial_balance=Decimal("0.00"))
    db_session.add_all([acc_a, acc_b])
    await db_session.commit()
    await db_session.refresh(acc_a)
    await db_session.refresh(acc_b)

    # 1. Create transfer with food memo
    idem_key = str(uuid.uuid4())
    payload = {
        "from_account_id": str(acc_a.id),
        "to_account_id": str(acc_b.id),
        "amount": "12.50",
        "currency": "USD",
        "memo": "Chipotle burrito lunch",
    }
    resp = await async_client.post(
        "/api/v1/transfers",
        json=payload,
        headers={"Idempotency-Key": idem_key},
    )
    assert resp.status_code == 201
    txn_id = uuid.UUID(resp.json()["transaction_id"])

    # 2. Process outbox batch
    processed = await process_outbox_batch(
        db=db_session,
        categorizer=RuleBasedCategorizer(),
        batch_size=10,
        transaction_ids=[txn_id],
    )
    assert processed >= 1

    # 3. Assert outbox record is DONE
    outbox_stmt = select(Outbox).where(Outbox.transaction_id == txn_id)
    outbox_entry = (await db_session.execute(outbox_stmt)).scalar_one()
    assert outbox_entry.status == "DONE"
    assert outbox_entry.attempts == 1

    # 4. Assert transaction record now has ai_category populated
    txn = await db_session.get(Transaction, txn_id)
    assert txn is not None
    assert txn.ai_category == "Food & Dining"


@pytest.mark.asyncio
async def test_outbox_worker_retry_and_failure_fallback(db_session: AsyncSession) -> None:
    """Verify worker retries failing tasks and marks status=FAILED with fallback after 3 attempts."""
    # 1. Create dummy transaction and outbox entry
    acc = Account(currency="USD", balance=Decimal("100.00"), initial_balance=Decimal("100.00"))
    db_session.add(acc)
    await db_session.flush()

    txn = Transaction(
        from_account_id=acc.id,
        to_account_id=acc.id,
        amount=Decimal("10.00"),
        status="COMPLETED",
        memo="Failing memo test",
    )
    db_session.add(txn)
    await db_session.flush()

    outbox_entry = Outbox(
        transaction_id=txn.id,
        status="PENDING",
        attempts=0,
    )
    db_session.add(outbox_entry)
    await db_session.commit()

    # 2. Process with failing categorizer 3 times
    failing_categorizer = FakeCategorizer(should_fail=True)

    for expected_attempt in range(1, 4):
        await process_outbox_batch(
            db=db_session,
            categorizer=failing_categorizer,
            batch_size=10,
            transaction_ids=[txn.id],
        )
        await db_session.refresh(outbox_entry)
        assert outbox_entry.attempts == expected_attempt

    # 3. On 3rd failure, status must transition to FAILED and category to Uncategorized
    assert outbox_entry.status == "FAILED"
    await db_session.refresh(txn)
    assert txn.ai_category == "Uncategorized"


@pytest.mark.asyncio
async def test_outbox_concurrent_workers_skip_locked(db_session: AsyncSession) -> None:
    """Verify multiple concurrent outbox workers process disjoint sets of rows using SKIP LOCKED."""
    # 1. Create account and 10 transactions with outbox records
    acc = Account(currency="USD", balance=Decimal("1000.00"), initial_balance=Decimal("1000.00"))
    db_session.add(acc)
    await db_session.flush()

    txns = []
    outboxes = []
    for i in range(10):
        t = Transaction(
            from_account_id=acc.id,
            to_account_id=acc.id,
            amount=Decimal("5.00"),
            status="COMPLETED",
            memo=f"Uber trip #{i}",
        )
        txns.append(t)
    db_session.add_all(txns)
    await db_session.flush()

    for t in txns:
        outboxes.append(Outbox(transaction_id=t.id, status="PENDING", attempts=0))
    db_session.add_all(outboxes)
    await db_session.commit()

    scoped_txn_ids = [t.id for t in txns]

    # 2. Run two workers concurrently with separate sessions, each claiming batch_size=5
    async def worker_task() -> int:
        async with TestingSessionLocal() as session:
            return await process_outbox_batch(
                db=session,
                categorizer=RuleBasedCategorizer(),
                batch_size=5,
                transaction_ids=scoped_txn_ids,
            )

    results = await asyncio.gather(worker_task(), worker_task())

    # 3. Assert both workers claimed 5 records each without collision
    assert results == [5, 5], f"Expected both workers to process 5 items, got {results}"

    # Verify all 10 are now DONE
    async with TestingSessionLocal() as verify_session:
        done_entries = (
            (
                await verify_session.execute(
                    select(Outbox).where(Outbox.transaction_id.in_([t.id for t in txns]))
                )
            )
            .scalars()
            .all()
        )
        assert len(done_entries) == 10
        assert all(e.status == "DONE" for e in done_entries)
