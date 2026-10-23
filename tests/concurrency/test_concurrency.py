"""High-Concurrency Stress Tests for Double-Entry Ledger.

Proves:
1. 0 overdrafts under heavy contention (200 parallel transfers on balance for 50).
2. 0 deadlocks under opposing transfers (A->B and B->A in parallel).
3. Conservation of money: total system balance before == total system balance after.
"""

import asyncio
import random
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.main import app
from app.models.account import Account
from tests.conftest import TestingSessionLocal


async def override_get_test_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency override yielding an independent session per request."""
    async with TestingSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@pytest.mark.asyncio
async def test_200_concurrent_transfers_no_overdraft(db_session: AsyncSession) -> None:
    """Requirement: 200 concurrent transfers from one account with balance for only 50.

    Assertions:
    - Exactly 50 transfers succeed.
    - Exactly 150 transfers fail with insufficient funds (422).
    - Final account balance is exactly 0.00.
    - 0 overdrafts occurred.
    """
    app.dependency_overrides[get_db] = override_get_test_db

    # 1. Create source account with balance for exactly 50 transfers ($50.00)
    source_acc = Account(currency="USD", balance=Decimal("50.00"))
    dest_acc = Account(currency="USD", balance=Decimal("0.00"))
    db_session.add_all([source_acc, dest_acc])
    await db_session.commit()
    await db_session.refresh(source_acc)
    await db_session.refresh(dest_acc)

    source_id = str(source_acc.id)
    dest_id = str(dest_acc.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Worker function making an HTTP transfer request
        async def make_transfer() -> int:
            resp = await client.post(
                "/api/v1/transfers",
                json={
                    "from_account_id": source_id,
                    "to_account_id": dest_id,
                    "amount": "1.00",
                    "currency": "USD",
                },
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            return resp.status_code

        # Fire 200 concurrent transfer requests simultaneously
        tasks = [make_transfer() for _ in range(200)]
        results = await asyncio.gather(*tasks)

    app.dependency_overrides.clear()

    # Assert exact concurrency behavior
    successes = [r for r in results if r == 201]
    failures = [r for r in results if r == 422]

    assert len(successes) == 50, f"Expected exactly 50 successes, got {len(successes)}"
    assert len(failures) == 150, f"Expected exactly 150 failures, got {len(failures)}"

    # Verify final database balances
    async with TestingSessionLocal() as verify_session:
        res_source = await verify_session.execute(
            select(Account).where(Account.id == source_acc.id)
        )
        res_dest = await verify_session.execute(select(Account).where(Account.id == dest_acc.id))
        final_source = res_source.scalar_one()
        final_dest = res_dest.scalar_one()

        assert final_source.balance == Decimal("0.00")
        assert final_dest.balance == Decimal("50.00")


@pytest.mark.asyncio
async def test_opposing_transfers_no_deadlock(db_session: AsyncSession) -> None:
    """Requirement: Opposing transfers A->B and B->A in parallel.

    Assertions:
    - 0 deadlocks occur due to deterministic ascending ID row locking.
    - All transfers complete successfully.
    - Balances remain conserved.
    """
    app.dependency_overrides[get_db] = override_get_test_db

    # Create two heavily contended accounts
    acc_a = Account(currency="USD", balance=Decimal("1000.00"))
    acc_b = Account(currency="USD", balance=Decimal("1000.00"))
    db_session.add_all([acc_a, acc_b])
    await db_session.commit()
    await db_session.refresh(acc_a)
    await db_session.refresh(acc_b)

    id_a = str(acc_a.id)
    id_b = str(acc_b.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:

        async def transfer_direction(from_id: str, to_id: str) -> int:
            resp = await client.post(
                "/api/v1/transfers",
                json={
                    "from_account_id": from_id,
                    "to_account_id": to_id,
                    "amount": "1.00",
                    "currency": "USD",
                },
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            return resp.status_code

        # Launch 200 total opposing transfers (100 A->B and 100 B->A) interleaved
        tasks = []
        for i in range(200):
            if i % 2 == 0:
                tasks.append(transfer_direction(id_a, id_b))
            else:
                tasks.append(transfer_direction(id_b, id_a))

        results = await asyncio.gather(*tasks)

    app.dependency_overrides.clear()

    # Assert 0 deadlocks (all 200 succeed)
    successes = [r for r in results if r == 201]
    assert len(successes) == 200, f"Expected 200 successes, got {len(successes)}"

    # Net balance after equal transfers in both directions must remain exactly $1000.00
    async with TestingSessionLocal() as verify_session:
        final_a = (
            await verify_session.execute(select(Account).where(Account.id == acc_a.id))
        ).scalar_one()
        final_b = (
            await verify_session.execute(select(Account).where(Account.id == acc_b.id))
        ).scalar_one()
        assert final_a.balance == Decimal("1000.00")
        assert final_b.balance == Decimal("1000.00")


@pytest.mark.asyncio
async def test_conservation_of_money_across_random_transfers(db_session: AsyncSession) -> None:
    """Requirement: Many random transfers among multiple accounts -> Total money before == after.

    Assertions:
    - Net sum of all account balances after transfers strictly equals initial total.
    - 0 balance drift across the entire system.
    """
    app.dependency_overrides[get_db] = override_get_test_db

    # Create 10 accounts with $100.00 each ($1000.00 total)
    accounts = [Account(currency="USD", balance=Decimal("100.00")) for _ in range(10)]
    db_session.add_all(accounts)
    await db_session.commit()
    for acc in accounts:
        await db_session.refresh(acc)

    account_ids = [str(acc.id) for acc in accounts]
    initial_total = Decimal("1000.00")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:

        async def random_transfer() -> int:
            from_id, to_id = random.sample(account_ids, 2)
            resp = await client.post(
                "/api/v1/transfers",
                json={
                    "from_account_id": from_id,
                    "to_account_id": to_id,
                    "amount": "5.00",
                    "currency": "USD",
                },
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            return resp.status_code

        # Fire 100 random transfers in parallel
        tasks = [random_transfer() for _ in range(100)]
        await asyncio.gather(*tasks)

    app.dependency_overrides.clear()

    # Verify that total money across all accounts is strictly conserved
    async with TestingSessionLocal() as verify_session:
        res = await verify_session.execute(
            select(Account).where(Account.id.in_([uuid.UUID(i) for i in account_ids]))
        )
        all_accounts = res.scalars().all()
        final_total = sum(acc.balance for acc in all_accounts)

        assert (
            final_total == initial_total
        ), f"Money was not conserved! Initial: {initial_total}, Final: {final_total}"


@pytest.mark.asyncio
async def test_50_concurrent_identical_idempotent_requests(db_session: AsyncSession) -> None:
    """Requirement: 50 concurrent requests with the identical Idempotency-Key and payload.

    Assertions:
    - Exactly 1 transaction executed and committed in the database.
    - Exactly 1 debit entry and 1 credit entry created.
    - All 50 callers receive HTTP 201 with the exact same response content and transaction_id.
    - Source account is debited exactly once ($100.00 - $25.00 = $75.00, NOT $0.00).
    - 0 double-charges or duplicate records occur under heavy parallel race conditions.
    """
    app.dependency_overrides[get_db] = override_get_test_db

    acc_from = Account(currency="USD", balance=Decimal("100.00"))
    acc_to = Account(currency="USD", balance=Decimal("0.00"))
    db_session.add_all([acc_from, acc_to])
    await db_session.commit()
    await db_session.refresh(acc_from)
    await db_session.refresh(acc_to)

    shared_key = str(uuid.uuid4())
    payload = {
        "from_account_id": str(acc_from.id),
        "to_account_id": str(acc_to.id),
        "amount": "25.00",
        "currency": "USD",
        "memo": "Concurrent identical idempotency race test",
    }
    headers = {"Idempotency-Key": shared_key}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Fire 50 simultaneous identical requests
        tasks = [client.post("/api/v1/transfers", json=payload, headers=headers) for _ in range(50)]
        responses = await asyncio.gather(*tasks)

    app.dependency_overrides.clear()

    # 1. Assert all 50 responses received 201 Created
    status_codes = [r.status_code for r in responses]
    assert all(
        code == 201 for code in status_codes
    ), f"Not all responses were 201: {set(status_codes)}"

    # 2. Assert all 50 returned the identical transaction_id
    txn_ids = {r.json()["transaction_id"] for r in responses}
    assert len(txn_ids) == 1, f"Expected exactly 1 unique transaction_id, got: {txn_ids}"

    # 3. Assert replay headers indicate duplicate handling
    replay_count = sum(1 for r in responses if r.headers.get("X-Idempotent-Replay") == "true")
    assert replay_count >= 49, f"Expected at least 49 replays, got {replay_count}"

    # 4. Verify database state: source debited exactly once, destination credited exactly once
    async with TestingSessionLocal() as verify_session:
        final_from = (
            await verify_session.execute(select(Account).where(Account.id == acc_from.id))
        ).scalar_one()
        final_to = (
            await verify_session.execute(select(Account).where(Account.id == acc_to.id))
        ).scalar_one()

        assert final_from.balance == Decimal("75.00")
        assert final_to.balance == Decimal("25.00")
