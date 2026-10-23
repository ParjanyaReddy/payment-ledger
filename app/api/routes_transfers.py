"""Transfer API Endpoints with Race-Safe Idempotency.

Handles HTTP POST requests for initiating double-entry transfers,
enforcing mandatory Idempotency-Key headers and atomic ON CONFLICT claims.
"""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
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
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyHashMismatchError,
    claim_or_get_idempotency,
    compute_request_hash,
    save_idempotency_response,
)
from app.services.transfer_service import execute_transfer

router = APIRouter(prefix="/transfers", tags=["Transfers"])


@router.post(
    "",
    response_model=TransferResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Execute an atomic money transfer with idempotency protection",
)
async def create_transfer(
    payload: TransferRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    idempotency_key: Annotated[
        uuid.UUID,
        Header(
            alias="Idempotency-Key",
            description="Unique UUID client key preventing duplicate transfer execution",
            examples=["123e4567-e89b-12d3-a456-426614174000"],
        ),
    ],
) -> JSONResponse:
    """Execute an atomic double-entry transfer with race-safe idempotency."""
    # 1. Compute deterministic request hash
    request_hash = compute_request_hash(
        method="POST",
        path="/api/v1/transfers",
        body=payload.model_dump(mode="json"),
    )

    # 2. Atomically claim idempotency key or retrieve cached response
    try:
        claim = await claim_or_get_idempotency(
            db=db,
            key=idempotency_key,
            request_hash=request_hash,
        )
    except IdempotencyHashMismatchError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(err),
        ) from err
    except IdempotencyConflictError as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(err),
        ) from err

    # 3. If key already completed, return cached response (exact replay)
    if not claim.is_new:
        return JSONResponse(
            status_code=claim.cached_status_code or status.HTTP_200_OK,
            content=claim.cached_body,
            headers={"X-Idempotent-Replay": "true"},
        )

    # 4. We own the key: execute the transfer
    try:
        result = await execute_transfer(
            db=db,
            from_account_id=payload.from_account_id,
            to_account_id=payload.to_account_id,
            amount=Decimal(payload.amount),
            currency=payload.currency,
            memo=payload.memo,
        )

        response_data = TransferResponse(
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
        ).model_dump(mode="json")

        # 5. Save cached response and commit in the same transaction
        await save_idempotency_response(
            db=db,
            key=idempotency_key,
            response_code=status.HTTP_201_CREATED,
            response_body=response_data,
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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(err),
        ) from err
    except Exception as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transfer execution failed: {err}",
        ) from err

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=response_data,
    )
