"""Transfer API Endpoints.

Handles HTTP POST requests for initiating double-entry transfers,
translating domain exceptions into standardized HTTP error responses.
"""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.transfer import (
    LedgerEntryResponse,
    TransferRequest,
    TransferResponse,
)
from app.services.exceptions import (
    AccountNotFoundError,
    CurrencyMismatchError,
    InsufficientFundsError,
    InvalidAmountError,
    SelfTransferError,
)
from app.services.transfer_service import execute_transfer

router = APIRouter(prefix="/transfers", tags=["Transfers"])


@router.post(
    "",
    response_model=TransferResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Execute an atomic money transfer",
)
async def create_transfer(
    payload: TransferRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TransferResponse:
    """Execute an atomic double-entry transfer between two accounts."""
    try:
        result = await execute_transfer(
            db=db,
            from_account_id=payload.from_account_id,
            to_account_id=payload.to_account_id,
            amount=Decimal(payload.amount),
            currency=payload.currency,
            memo=payload.memo,
        )
        await db.commit()
    except SelfTransferError as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err
    except (InvalidAmountError, CurrencyMismatchError) as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err
    except AccountNotFoundError as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except InsufficientFundsError as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(err),
        ) from err
    except Exception as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transfer execution failed: {err}",
        ) from err

    return TransferResponse(
        transaction_id=result.transaction.id,
        status=result.transaction.status,
        from_account_id=payload.from_account_id,
        to_account_id=payload.to_account_id,
        amount=f"{result.transaction.amount:.2f}",
        currency=payload.currency,
        memo=result.transaction.memo,
        from_account_balance=f"{result.from_account_balance:.2f}",
        to_account_balance=f"{result.to_account_balance:.2f}",
        entries=[
            LedgerEntryResponse.model_validate(result.debit_entry),
            LedgerEntryResponse.model_validate(result.credit_entry),
        ],
        created_at=result.transaction.created_at,
    )
