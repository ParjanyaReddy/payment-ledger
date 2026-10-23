import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.account import Account
from app.models.ledger_entry import LedgerEntry
from app.schemas.reconciliation import (
    ReconciliationResponse,
    ReconciliationStatusResponse,
)
from app.services.reconciliation import (
    get_reconciliation_status,
    run_reconciliation,
)

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])


@router.post(
    "/run",
    response_model=ReconciliationResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger an on-demand ledger reconciliation audit",
)
async def trigger_reconciliation(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReconciliationResponse:
    """Execute a complete audit of all accounts, transactions, and ledger entries."""
    return await run_reconciliation(db=db)


@router.get(
    "/status",
    response_model=ReconciliationStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve latest reconciliation audit status and system health",
)
async def fetch_reconciliation_status(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReconciliationStatusResponse:
    """Fetch the latest audit result, total run count, and current health."""
    return await get_reconciliation_status(db=db)


class TamperDrillRequest(BaseModel):
    """Payload for injecting intentional balance drift."""

    account_id: uuid.UUID | None = Field(default=None)
    drift_amount: str = Field(default="100.00")


@router.post(
    "/drill/tamper",
    status_code=status.HTTP_200_OK,
    summary="Inject deliberate balance corruption for audit verification demonstration",
)
async def tamper_balance_drill(
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: TamperDrillRequest | None = None,
) -> dict[str, str]:
    """Artificially tamper with an account balance via raw SQL update to test drift detection."""
    req = payload or TamperDrillRequest()
    drift = Decimal(req.drift_amount)

    if req.account_id:
        acc = await db.get(Account, req.account_id)
        if not acc:
            raise HTTPException(status_code=404, detail="Account not found")
        target_id = req.account_id
    else:
        # Pick the first account
        result = await db.execute(select(Account).limit(1))
        acc = result.scalar_one_or_none()
        if not acc:
            raise HTTPException(status_code=400, detail="No accounts exist to tamper")
        target_id = acc.id

    # Execute direct update bypassing the transfer engine
    stmt = update(Account).where(Account.id == target_id).values(balance=Account.balance + drift)
    await db.execute(stmt)
    await db.commit()

    return {
        "status": "TAMPERED",
        "account_id": str(target_id),
        "injected_drift": f"{drift:+.2f}",
        "message": "Direct SQL balance alteration executed. Run reconciliation to detect the drift.",
    }


@router.post(
    "/drill/heal",
    status_code=status.HTTP_200_OK,
    summary="Heal corrupted balance projections from immutable double-entry history",
)
async def heal_balances_drill(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Reconstruct all account cached balances from the immutable ledger entries."""
    # Query true balances from ledger entries + initial_balance
    credit_sum = func.coalesce(
        func.sum(
            case((LedgerEntry.direction == "CREDIT", LedgerEntry.amount), else_=Decimal("0.00"))
        ),
        Decimal("0.00"),
    )
    debit_sum = func.coalesce(
        func.sum(
            case((LedgerEntry.direction == "DEBIT", LedgerEntry.amount), else_=Decimal("0.00"))
        ),
        Decimal("0.00"),
    )

    stmt = (
        select(
            Account.id,
            Account.initial_balance,
            credit_sum.label("credits"),
            debit_sum.label("debits"),
        )
        .outerjoin(LedgerEntry, Account.id == LedgerEntry.account_id)
        .group_by(Account.id, Account.initial_balance)
    )

    rows = (await db.execute(stmt)).all()
    healed_count = 0
    for acc_id, init_bal, credits, debits in rows:
        true_balance = init_bal + credits - debits
        await db.execute(update(Account).where(Account.id == acc_id).values(balance=true_balance))
        healed_count += 1

    await db.commit()
    return {
        "status": "HEALED",
        "accounts_healed": str(healed_count),
        "message": "All cached balances successfully recomputed from immutable ledger entries.",
    }
