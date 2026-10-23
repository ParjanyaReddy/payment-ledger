"""Card Lifecycle and Payment Primitives API Routes.

Exposes REST endpoints for card authorizations, holds, captures, voids, and refunds.
Enforces balance hold guarantees, velocity fraud rules, and full double-entry settlement.
"""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.card import (
    CardAuthRequest,
    CardAuthResponse,
    CardCaptureRequest,
    CardRefundRequest,
    CardVoidRequest,
)
from app.services.card_service import (
    authorize_card_payment,
    capture_card_payment,
    get_card_authorization,
    list_card_authorizations_for_account,
    refund_card_payment,
    void_card_payment,
)
from app.services.exceptions import (
    AccountNotFoundError,
    CardAuthorizationExpiredError,
    CardAuthorizationNotFoundError,
    CurrencyMismatchError,
    InsufficientFundsError,
    InvalidAmountError,
    InvalidCardStateTransitionError,
    InvalidRefundAmountError,
    SelfTransferError,
    VelocityLimitExceededError,
)
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyHashMismatchError,
    claim_or_get_idempotency,
    compute_request_hash,
    save_idempotency_response,
)

router = APIRouter(prefix="/cards", tags=["Cards"])


@router.post(
    "/authorize",
    response_model=CardAuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Place an authorization hold on customer available balance",
)
async def create_card_authorization(
    payload: CardAuthRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    idempotency_key: Annotated[
        uuid.UUID | None,
        Header(
            alias="Idempotency-Key",
            description="Optional unique UUID key to prevent duplicate authorizations",
        ),
    ] = None,
) -> JSONResponse:
    """Authorize a card payment by placing a hold on available balance."""
    claim = None
    if idempotency_key:
        request_hash = compute_request_hash(
            method="POST",
            path="/api/v1/cards/authorize",
            body=payload.model_dump(mode="json"),
        )
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

        if not claim.is_new:
            return JSONResponse(
                status_code=claim.cached_status_code or status.HTTP_200_OK,
                content=claim.cached_body,
                headers={"X-Idempotent-Replay": "true"},
            )

    try:
        auth = await authorize_card_payment(
            db=db,
            account_id=payload.account_id,
            merchant_id=payload.merchant_id,
            amount=Decimal(payload.amount),
            currency=payload.currency,
            memo=payload.memo,
            hold_duration_hours=payload.hold_duration_hours,
            check_velocity=True,
        )
        await db.commit()
    except VelocityLimitExceededError as err:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(err)) from err
    except InsufficientFundsError as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(err),
        ) from err
    except AccountNotFoundError as err:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err
    except (SelfTransferError, CurrencyMismatchError) as err:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err
    except InvalidAmountError as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(err),
        ) from err

    response_data = CardAuthResponse.model_validate(auth).model_dump(mode="json")
    response_data["message"] = "Hold successfully placed against available balance"

    if idempotency_key and claim and claim.is_new:
        await save_idempotency_response(
            db=db,
            key=idempotency_key,
            response_code=status.HTTP_201_CREATED,
            response_body=response_data,
        )
        await db.commit()

    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response_data)


@router.post(
    "/{authorization_id}/capture",
    response_model=CardAuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Capture an authorization hold into a settled double-entry transfer",
)
async def capture_card(
    authorization_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: CardCaptureRequest | None = None,
) -> JSONResponse:
    """Capture an authorized hold, executing double-entry ledger settlement."""
    req = payload or CardCaptureRequest()
    capture_dec = Decimal(req.amount) if req.amount is not None else None
    try:
        auth, txn = await capture_card_payment(
            db=db,
            authorization_id=authorization_id,
            capture_amount=capture_dec,
        )
        await db.commit()
    except CardAuthorizationNotFoundError as err:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err
    except (InvalidCardStateTransitionError, CardAuthorizationExpiredError) as err:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err
    except InvalidAmountError as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(err),
        ) from err

    response_data = CardAuthResponse.model_validate(auth).model_dump(mode="json")
    response_data["message"] = (
        f"Authorization captured: {auth.captured_amount} settled via transaction {txn.id}"
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=response_data)


@router.post(
    "/{authorization_id}/void",
    response_model=CardAuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Void an active authorization hold before capture",
)
async def void_card(
    authorization_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: CardVoidRequest | None = None,
) -> JSONResponse:
    """Void an active hold, immediately restoring available balance with zero ledger mutation."""
    req = payload or CardVoidRequest()
    try:
        auth = await void_card_payment(
            db=db,
            authorization_id=authorization_id,
            reason=req.reason,
        )
        await db.commit()
    except CardAuthorizationNotFoundError as err:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err
    except InvalidCardStateTransitionError as err:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err

    response_data = CardAuthResponse.model_validate(auth).model_dump(mode="json")
    response_data["message"] = "Authorization voided; hold released with zero ledger movements"
    return JSONResponse(status_code=status.HTTP_200_OK, content=response_data)


@router.post(
    "/{authorization_id}/refund",
    response_model=CardAuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Refund a captured payment via reverse double-entry transfer",
)
async def refund_card(
    authorization_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: CardRefundRequest | None = None,
) -> JSONResponse:
    """Execute a reverse double-entry refund on a captured payment."""
    req = payload or CardRefundRequest()
    refund_dec = Decimal(req.amount) if req.amount is not None else None
    try:
        auth, txn = await refund_card_payment(
            db=db,
            authorization_id=authorization_id,
            refund_amount=refund_dec,
            reason=req.reason,
        )
        await db.commit()
    except CardAuthorizationNotFoundError as err:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err
    except InvalidCardStateTransitionError as err:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err
    except (InvalidRefundAmountError, InsufficientFundsError) as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(err),
        ) from err

    response_data = CardAuthResponse.model_validate(auth).model_dump(mode="json")
    response_data["message"] = (
        f"Refund processed: {refund_dec or auth.refunded_amount} returned via transaction {txn.id}"
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=response_data)


@router.get(
    "/{authorization_id}",
    response_model=CardAuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve details and state of a card authorization",
)
async def get_card(
    authorization_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    """Fetch authorization record by UUID."""
    try:
        auth = await get_card_authorization(db=db, authorization_id=authorization_id)
    except CardAuthorizationNotFoundError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err

    response_data = CardAuthResponse.model_validate(auth).model_dump(mode="json")
    return JSONResponse(status_code=status.HTTP_200_OK, content=response_data)


@router.get(
    "/account/{account_id}",
    response_model=list[CardAuthResponse],
    status_code=status.HTTP_200_OK,
    summary="List card authorizations for a specific account",
)
async def list_account_cards(
    account_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    """List recent authorizations involving an account."""
    auths = await list_card_authorizations_for_account(db=db, account_id=account_id)
    response_data = [CardAuthResponse.model_validate(a).model_dump(mode="json") for a in auths]
    return JSONResponse(status_code=status.HTTP_200_OK, content=response_data)
