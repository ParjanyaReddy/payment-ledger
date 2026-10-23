"""Integration Tests for Web Auditor Dashboard and Interactive Demonstration Endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_dashboard_endpoint_serves_html(async_client: AsyncClient) -> None:
    """Verify that /dashboard returns HTTP 200 with HTML dashboard interface."""
    response = await async_client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "LEDGER CORE" in response.text
    assert "Double-Entry Financial Accounting Engine" in response.text


@pytest.mark.asyncio
async def test_list_transactions_and_ledger_entries_endpoints(
    async_client: AsyncClient,
) -> None:
    """Verify that /api/v1/transfers and /api/v1/transfers/entries return structured lists."""
    txns_res = await async_client.get("/api/v1/transfers")
    assert txns_res.status_code == 200
    assert isinstance(txns_res.json(), list)

    entries_res = await async_client.get("/api/v1/transfers/entries")
    assert entries_res.status_code == 200
    assert isinstance(entries_res.json(), list)


@pytest.mark.asyncio
async def test_reconciliation_tamper_and_heal_drills(async_client: AsyncClient) -> None:
    """Verify that the interactive tamper drill injects drift and the heal drill restores integrity."""
    # 1. Create a clean account
    acc_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "500.00"},
    )
    acc_id = acc_res.json()["id"]

    # 2. Inject deliberate balance corruption via the drill endpoint
    tamper_res = await async_client.post(
        "/api/v1/reconciliation/drill/tamper",
        json={"account_id": acc_id, "drift_amount": "75.00"},
    )
    assert tamper_res.status_code == 200
    assert tamper_res.json()["status"] == "TAMPERED"

    # 3. Verify reconciliation flags DRIFT_DETECTED
    audit_res = await async_client.post("/api/v1/reconciliation/run")
    assert audit_res.status_code == 200
    report = audit_res.json()
    assert report["status"] == "DRIFT_DETECTED"
    assert report["drifts_detected"] >= 1

    # 4. Heal balance projections from immutable double-entry history
    heal_res = await async_client.post("/api/v1/reconciliation/drill/heal")
    assert heal_res.status_code == 200
    assert heal_res.json()["status"] == "HEALED"

    # 5. Verify reconciliation now passes with HEALTHY
    audit_clean = await async_client.post("/api/v1/reconciliation/run")
    assert audit_clean.status_code == 200
    assert audit_clean.json()["status"] == "HEALTHY"
    assert audit_clean.json()["drifts_detected"] == 0
