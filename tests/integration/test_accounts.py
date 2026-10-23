"""Integration Tests for Account Management Endpoints."""

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_get_account(async_client: AsyncClient) -> None:
    """Verify creating an account and retrieving it by its ID."""
    create_payload = {
        "currency": "USD",
        "initial_balance": "500.00",
    }
    create_res = await async_client.post("/api/v1/accounts", json=create_payload)
    assert create_res.status_code == 201
    created_data = create_res.json()

    assert "id" in created_data
    account_id = created_data["id"]
    assert created_data["currency"] == "USD"
    assert created_data["balance"] == "500.00"
    assert created_data["version"] == 0

    # Retrieve account by ID
    get_res = await async_client.get(f"/api/v1/accounts/{account_id}")
    assert get_res.status_code == 200
    retrieved_data = get_res.json()
    assert retrieved_data["id"] == account_id
    assert retrieved_data["balance"] == "500.00"
    assert retrieved_data["currency"] == "USD"


@pytest.mark.asyncio
async def test_get_nonexistent_account(async_client: AsyncClient) -> None:
    """Verify 404 Not Found response when requesting unknown UUID."""
    random_id = uuid.uuid4()
    response = await async_client.get(f"/api/v1/accounts/{random_id}")
    assert response.status_code == 404
    assert f"Account with ID '{random_id}' was not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_accounts(async_client: AsyncClient) -> None:
    """Verify listing accounts returns a list containing created accounts."""
    # Create an account
    await async_client.post(
        "/api/v1/accounts",
        json={"currency": "EUR", "initial_balance": "120.00"},
    )

    list_res = await async_client.get("/api/v1/accounts?limit=10")
    assert list_res.status_code == 200
    accounts = list_res.json()
    assert isinstance(accounts, list)
    assert len(accounts) >= 1
