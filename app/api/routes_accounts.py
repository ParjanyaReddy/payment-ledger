"""Account Management API Endpoints.

Provides HTTP routes for creating and retrieving account records.
"""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.account import Account
from app.schemas.account import AccountCreate, AccountResponse

router = APIRouter(prefix="/accounts", tags=["Accounts"])


@router.post(
    "",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
)
async def create_account(
    payload: AccountCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Account:
    """Create a new account with a specified currency and optional initial balance."""
    new_account = Account(
        currency=payload.currency,
        balance=Decimal(payload.initial_balance),
        version=0,
    )
    db.add(new_account)
    await db.commit()
    await db.refresh(new_account)
    return new_account


@router.get(
    "/{account_id}",
    response_model=AccountResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve account by ID",
)
async def get_account(
    account_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Account:
    """Fetch an account by its unique UUID identifier."""
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account with ID '{account_id}' was not found",
        )
    return account


@router.get(
    "",
    response_model=list[AccountResponse],
    status_code=status.HTTP_200_OK,
    summary="List all accounts",
)
async def list_accounts(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 50,
    offset: int = 0,
) -> list[Account]:
    """List accounts ordered by creation date."""
    result = await db.execute(
        select(Account).order_by(Account.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())
