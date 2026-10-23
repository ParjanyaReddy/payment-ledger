"""Integration Tests for Card Lifecycle, Holds, and Velocity Limits API Endpoints."""

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_card_full_lifecycle_auth_capture_refund(async_client: AsyncClient) -> None:
    """Test full card payment lifecycle: Authorize -> Capture -> Partial Refund -> Full Refund."""
    # 1. Create customer and merchant accounts
    customer_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "1000.00"},
    )
    assert customer_res.status_code == 201
    customer_id = customer_res.json()["id"]

    merchant_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "0.00"},
    )
    assert merchant_res.status_code == 201
    merchant_id = merchant_res.json()["id"]

    # 2. Authorize $150.00
    auth_res = await async_client.post(
        "/api/v1/cards/authorize",
        json={
            "account_id": customer_id,
            "merchant_id": merchant_id,
            "amount": "150.00",
            "currency": "USD",
            "memo": "Hotel reservation deposit",
        },
    )
    assert auth_res.status_code == 201
    auth_data = auth_res.json()
    auth_id = auth_data["id"]
    assert auth_data["status"] == "AUTHORIZED"
    assert auth_data["amount"] == "150.00"

    # Verify balances: Booked unchanged, hold placed, available balance reduced
    c_check = await async_client.get(f"/api/v1/accounts/{customer_id}")
    assert c_check.json()["balance"] == "1000.00"
    assert c_check.json()["holds"] == "150.00"
    assert c_check.json()["available_balance"] == "850.00"

    m_check = await async_client.get(f"/api/v1/accounts/{merchant_id}")
    assert m_check.json()["balance"] == "0.00"

    # 3. Capture $150.00
    capture_res = await async_client.post(
        f"/api/v1/cards/{auth_id}/capture",
        json={"amount": "150.00"},
    )
    assert capture_res.status_code == 200
    assert capture_res.json()["status"] == "CAPTURED"
    assert capture_res.json()["captured_amount"] == "150.00"
    assert capture_res.json()["transaction_id"] is not None

    # Verify balances: Hold released, booked balance debited from customer, credited to merchant
    c_after_cap = await async_client.get(f"/api/v1/accounts/{customer_id}")
    assert c_after_cap.json()["balance"] == "850.00"
    assert c_after_cap.json()["holds"] == "0.00"
    assert c_after_cap.json()["available_balance"] == "850.00"

    m_after_cap = await async_client.get(f"/api/v1/accounts/{merchant_id}")
    assert m_after_cap.json()["balance"] == "150.00"

    # 4. Partial Refund of $50.00
    refund1_res = await async_client.post(
        f"/api/v1/cards/{auth_id}/refund",
        json={"amount": "50.00", "reason": "Room service discount"},
    )
    assert refund1_res.status_code == 200
    assert refund1_res.json()["status"] == "CAPTURED"
    assert refund1_res.json()["refunded_amount"] == "50.00"

    c_after_ref1 = await async_client.get(f"/api/v1/accounts/{customer_id}")
    assert c_after_ref1.json()["balance"] == "900.00"
    m_after_ref1 = await async_client.get(f"/api/v1/accounts/{merchant_id}")
    assert m_after_ref1.json()["balance"] == "100.00"

    # 5. Full remaining refund of $100.00
    refund2_res = await async_client.post(
        f"/api/v1/cards/{auth_id}/refund",
        json={"amount": "100.00", "reason": "Remaining stay refunded"},
    )
    assert refund2_res.status_code == 200
    assert refund2_res.json()["status"] == "REFUNDED"
    assert refund2_res.json()["refunded_amount"] == "150.00"

    c_final = await async_client.get(f"/api/v1/accounts/{customer_id}")
    assert c_final.json()["balance"] == "1000.00"
    m_final = await async_client.get(f"/api/v1/accounts/{merchant_id}")
    assert m_final.json()["balance"] == "0.00"


@pytest.mark.asyncio
async def test_card_authorization_and_void(async_client: AsyncClient) -> None:
    """Test Authorize -> Void lifecycle without money movement."""
    customer_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "500.00"},
    )
    customer_id = customer_res.json()["id"]

    merchant_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "0.00"},
    )
    merchant_id = merchant_res.json()["id"]

    # 1. Authorize $200.00
    auth_res = await async_client.post(
        "/api/v1/cards/authorize",
        json={
            "account_id": customer_id,
            "merchant_id": merchant_id,
            "amount": "200.00",
            "currency": "USD",
            "memo": "Rental car security hold",
        },
    )
    assert auth_res.status_code == 201
    auth_id = auth_res.json()["id"]

    # Available balance drops to 300.00
    c_check = await async_client.get(f"/api/v1/accounts/{customer_id}")
    assert c_check.json()["balance"] == "500.00"
    assert c_check.json()["holds"] == "200.00"
    assert c_check.json()["available_balance"] == "300.00"

    # 2. Void authorization
    void_res = await async_client.post(
        f"/api/v1/cards/{auth_id}/void",
        json={"reason": "Car returned without damages"},
    )
    assert void_res.status_code == 200
    assert void_res.json()["status"] == "VOIDED"

    # Holds cleared, available balance restored to 500.00
    c_after_void = await async_client.get(f"/api/v1/accounts/{customer_id}")
    assert c_after_void.json()["balance"] == "500.00"
    assert c_after_void.json()["holds"] == "0.00"
    assert c_after_void.json()["available_balance"] == "500.00"


@pytest.mark.asyncio
async def test_card_partial_capture(async_client: AsyncClient) -> None:
    """Test partial capture settles lower amount and releases the full hold."""
    customer_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "400.00"},
    )
    customer_id = customer_res.json()["id"]

    merchant_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "0.00"},
    )
    merchant_id = merchant_res.json()["id"]

    # Authorize $250.00 (e.g. gas station estimated hold)
    auth_res = await async_client.post(
        "/api/v1/cards/authorize",
        json={
            "account_id": customer_id,
            "merchant_id": merchant_id,
            "amount": "250.00",
            "currency": "USD",
            "memo": "Fuel pump pre-auth",
        },
    )
    auth_id = auth_res.json()["id"]

    # Settle actual fuel pumped ($75.00)
    capture_res = await async_client.post(
        f"/api/v1/cards/{auth_id}/capture",
        json={"amount": "75.00"},
    )
    assert capture_res.status_code == 200
    assert capture_res.json()["captured_amount"] == "75.00"

    # Entire $250 hold is released; customer charged only $75.00
    c_check = await async_client.get(f"/api/v1/accounts/{customer_id}")
    assert c_check.json()["balance"] == "325.00"
    assert c_check.json()["holds"] == "0.00"
    assert c_check.json()["available_balance"] == "325.00"

    m_check = await async_client.get(f"/api/v1/accounts/{merchant_id}")
    assert m_check.json()["balance"] == "75.00"


@pytest.mark.asyncio
async def test_holds_prevent_direct_transfer_overdraft(async_client: AsyncClient) -> None:
    """Verify that funds on hold cannot be transferred via regular wire transfers."""
    customer_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "100.00"},
    )
    customer_id = customer_res.json()["id"]

    merchant_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "0.00"},
    )
    merchant_id = merchant_res.json()["id"]

    other_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "0.00"},
    )
    other_id = other_res.json()["id"]

    # Authorize $80.00 -> available balance becomes $20.00
    await async_client.post(
        "/api/v1/cards/authorize",
        json={
            "account_id": customer_id,
            "merchant_id": merchant_id,
            "amount": "80.00",
            "currency": "USD",
        },
    )

    # Attempt direct transfer of $50.00 -> should fail because available is only 20.00
    idem_key = str(uuid.uuid4())
    transfer_res = await async_client.post(
        "/api/v1/transfers",
        json={
            "from_account_id": customer_id,
            "to_account_id": other_id,
            "amount": "50.00",
            "currency": "USD",
        },
        headers={"Idempotency-Key": idem_key},
    )
    assert transfer_res.status_code == 422
    assert "Insufficient funds" in transfer_res.json()["detail"]
    assert "available 20.00" in transfer_res.json()["detail"]


@pytest.mark.asyncio
async def test_card_authorization_idempotency_replay(async_client: AsyncClient) -> None:
    """Verify that card authorization supports idempotency replay without double holds."""
    customer_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "200.00"},
    )
    customer_id = customer_res.json()["id"]

    merchant_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "0.00"},
    )
    merchant_id = merchant_res.json()["id"]

    idem_key = str(uuid.uuid4())
    payload = {
        "account_id": customer_id,
        "merchant_id": merchant_id,
        "amount": "50.00",
        "currency": "USD",
        "memo": "Idempotent payment",
    }

    # 1. First authorization
    res1 = await async_client.post(
        "/api/v1/cards/authorize",
        json=payload,
        headers={"Idempotency-Key": idem_key},
    )
    assert res1.status_code == 201
    auth_id = res1.json()["id"]

    # 2. Replay with identical key
    res2 = await async_client.post(
        "/api/v1/cards/authorize",
        json=payload,
        headers={"Idempotency-Key": idem_key},
    )
    assert res2.status_code == 201
    assert res2.headers.get("X-Idempotent-Replay") == "true"
    assert res2.json()["id"] == auth_id

    # Verify only ONE hold of $50 was placed
    c_check = await async_client.get(f"/api/v1/accounts/{customer_id}")
    assert c_check.json()["holds"] == "50.00"
    assert c_check.json()["available_balance"] == "150.00"


@pytest.mark.asyncio
async def test_invalid_state_transitions_rejected(async_client: AsyncClient) -> None:
    """Verify that illegal card state transitions are rejected with HTTP 400/422."""
    customer_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "300.00"},
    )
    customer_id = customer_res.json()["id"]

    merchant_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "0.00"},
    )
    merchant_id = merchant_res.json()["id"]

    # 1. Authorize $100.00
    auth_res = await async_client.post(
        "/api/v1/cards/authorize",
        json={
            "account_id": customer_id,
            "merchant_id": merchant_id,
            "amount": "100.00",
            "currency": "USD",
        },
    )
    auth_id = auth_res.json()["id"]

    # Attempting to refund an AUTHORIZED payment should fail (must be CAPTURED)
    refund_err = await async_client.post(
        f"/api/v1/cards/{auth_id}/refund",
        json={"amount": "50.00"},
    )
    assert refund_err.status_code == 400
    assert (
        "Cannot execute 'REFUND' on authorization in 'AUTHORIZED' status"
        in refund_err.json()["detail"]
    )

    # Capture it
    cap_res = await async_client.post(f"/api/v1/cards/{auth_id}/capture")
    assert cap_res.status_code == 200

    # Attempting to void a CAPTURED payment should fail
    void_err = await async_client.post(f"/api/v1/cards/{auth_id}/void")
    assert void_err.status_code == 400
    assert (
        "Cannot execute 'VOID' on authorization in 'CAPTURED' status" in void_err.json()["detail"]
    )

    # Attempting to refund more than captured ($150 > $100) should fail
    over_refund = await async_client.post(
        f"/api/v1/cards/{auth_id}/refund",
        json={"amount": "150.00"},
    )
    assert over_refund.status_code == 422
    assert "exceeds maximum eligible refund" in over_refund.json()["detail"]


@pytest.mark.asyncio
async def test_list_account_card_authorizations(async_client: AsyncClient) -> None:
    """Verify listing recent authorizations for an account."""
    acc_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "500.00"},
    )
    acc_id = acc_res.json()["id"]

    merch_res = await async_client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "initial_balance": "0.00"},
    )
    merch_id = merch_res.json()["id"]

    # Place two authorizations
    await async_client.post(
        "/api/v1/cards/authorize",
        json={"account_id": acc_id, "merchant_id": merch_id, "amount": "10.00", "currency": "USD"},
    )
    await async_client.post(
        "/api/v1/cards/authorize",
        json={"account_id": acc_id, "merchant_id": merch_id, "amount": "20.00", "currency": "USD"},
    )

    list_res = await async_client.get(f"/api/v1/cards/account/{acc_id}")
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) >= 2
