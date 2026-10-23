"""Integration Tests for Automated Ledger Reconciliation and Drift Detection."""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account


@pytest.mark.asyncio
async def test_reconciliation_healthy_system(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify reconciliation reports HEALTHY when balances match ledger history."""
    # 1. Create two accounts
    acc_a = Account(currency="USD", balance=Decimal("100.00"), initial_balance=Decimal("100.00"))
    acc_b = Account(currency="USD", balance=Decimal("50.00"), initial_balance=Decimal("50.00"))
    db_session.add_all([acc_a, acc_b])
    await db_session.commit()
    await db_session.refresh(acc_a)
    await db_session.refresh(acc_b)

    # 2. Execute a valid transfer
    idem_key = str(uuid.uuid4())
    payload = {
        "from_account_id": str(acc_a.id),
        "to_account_id": str(acc_b.id),
        "amount": "25.00",
        "currency": "USD",
        "memo": "Reconciliation healthy test",
    }
    tx_resp = await async_client.post(
        "/api/v1/transfers",
        json=payload,
        headers={"Idempotency-Key": idem_key},
    )
    assert tx_resp.status_code == 201

    # 3. Trigger reconciliation run
    audit_resp = await async_client.post("/api/v1/reconciliation/run")
    assert audit_resp.status_code == 200
    report = audit_resp.json()

    assert report["status"] == "HEALTHY"
    assert report["drifts_detected"] == 0
    assert report["discrepancies"] == []
    assert report["accounts_audited"] >= 2
    assert report["transactions_audited"] >= 1
    assert float(report["execution_time_ms"]) >= 0.0


@pytest.mark.asyncio
async def test_reconciliation_detects_deliberate_balance_corruption(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test Drill: Deliberately tamper with an account balance in SQL and verify auditor flags it."""
    # 1. Create account with initial balance $200.00
    victim_acc = Account(
        currency="USD",
        balance=Decimal("200.00"),
        initial_balance=Decimal("200.00"),
    )
    db_session.add(victim_acc)
    await db_session.commit()
    await db_session.refresh(victim_acc)
    victim_id = str(victim_acc.id)

    # 2. DELIBERATE TAMPERING DRILL:
    try:
        # Directly manipulate the cached balance projection via raw SQL without writing any ledger entries.
        # Simulates an attacker or a runaway rogue admin script updating balance from $200.00 to $9999.00.
        await db_session.execute(
            text("UPDATE accounts SET balance = 9999.00 WHERE id = :acc_id"),
            {"acc_id": victim_acc.id},
        )
        await db_session.commit()

        # 3. Trigger reconciliation audit
        audit_resp = await async_client.post("/api/v1/reconciliation/run")
        assert audit_resp.status_code == 200
        report = audit_resp.json()

        # 4. Assert auditor caught the corruption
        assert report["status"] == "DRIFT_DETECTED"
        assert report["drifts_detected"] >= 1

        # Find the discrepancy for our victim account
        victim_discrepancy = next(
            (d for d in report["discrepancies"] if d["account_id"] == victim_id),
            None,
        )
        assert victim_discrepancy is not None, f"Expected {victim_id} in {report['discrepancies']}"
        assert victim_discrepancy["actual_balance"] == "9999.00"
        assert victim_discrepancy["expected_balance"] == "200.00"
        assert victim_discrepancy["drift"] == "+9799.00"
        assert "Balance drift detected" in victim_discrepancy["reason"]
    finally:
        # Clean up corrupted test account to prevent polluting subsequent test runs
        await db_session.execute(
            text("DELETE FROM accounts WHERE id = :acc_id"),
            {"acc_id": victim_acc.id},
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_reconciliation_status_endpoint(async_client: AsyncClient) -> None:
    """Verify querying reconciliation status returns history and system health."""
    # 1. Run audit first
    await async_client.post("/api/v1/reconciliation/run")

    # 2. Query status endpoint
    status_resp = await async_client.get("/api/v1/reconciliation/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()

    assert status_data["system_health"] in ("HEALTHY", "DRIFT_DETECTED")
    assert status_data["total_runs"] >= 1
    assert status_data["last_audited_at"] is not None
    assert status_data["latest_run"] is not None
