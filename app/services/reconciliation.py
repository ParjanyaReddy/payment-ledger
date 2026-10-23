# CORE LOGIC: understand this file line by line.
"""Automated Ledger Reconciliation and Balance Drift Detection Engine.

Mathematically verifies two foundational financial accounting invariants:
1. Account Balance Invariant:
   For every account: Cached Balance == Initial Balance + Sum(Credits) - Sum(Debits).
   Guarantees that the cached projection in the accounts table has not drifted
   due to silent corruption, race conditions, or unauthorized manual updates.

2. Double-Entry Invariant:
   For every transaction: Sum(Credits) == Sum(Debits) (i.e. Net Sum of Entries == 0).
   Guarantees that no transaction created or destroyed money unilaterally.

Generates an audit report, persists the run into reconciliation_runs, and flags
any corrupted accounts with exact drift amounts for immediate operational triage.
"""

import time
import uuid
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.ledger_entry import LedgerEntry
from app.models.reconciliation_run import ReconciliationRun
from app.models.transaction import Transaction
from app.schemas.reconciliation import (
    DiscrepancyDetail,
    ReconciliationResponse,
    ReconciliationStatusResponse,
)


async def run_reconciliation(db: AsyncSession) -> ReconciliationResponse:
    """Execute a comprehensive ledger audit across all accounts and transactions.

    Executes aggregation queries across accounts and transactions to detect
    any discrepancy between stored balances and immutable double-entry ledger entries.

    Args:
        db: Active asynchronous SQLAlchemy database session.

    Returns:
        ReconciliationResponse detailing total entities checked and any detected drift.
    """
    start_time = time.perf_counter()

    # -------------------------------------------------------------------------
    # 1. Audit Account Balance Invariant:
    #    Expected = initial_balance + sum(credits) - sum(debits)
    # -------------------------------------------------------------------------
    credit_sum = func.coalesce(
        func.sum(
            case((LedgerEntry.direction == "CREDIT", LedgerEntry.amount), else_=Decimal("0.00"))
        ),
        Decimal("0.00"),
    ).label("total_credits")

    debit_sum = func.coalesce(
        func.sum(
            case((LedgerEntry.direction == "DEBIT", LedgerEntry.amount), else_=Decimal("0.00"))
        ),
        Decimal("0.00"),
    ).label("total_debits")

    account_audit_stmt = (
        select(
            Account.id,
            Account.currency,
            Account.balance,
            Account.initial_balance,
            credit_sum,
            debit_sum,
        )
        .outerjoin(LedgerEntry, Account.id == LedgerEntry.account_id)
        .group_by(Account.id, Account.currency, Account.balance, Account.initial_balance)
    )

    account_rows = (await db.execute(account_audit_stmt)).all()
    accounts_audited = len(account_rows)
    discrepancies: list[DiscrepancyDetail] = []

    for row in account_rows:
        acc_id, currency, actual_bal, initial_bal, total_credits, total_debits = row
        expected_bal = initial_bal + total_credits - total_debits
        drift = actual_bal - expected_bal

        if drift != Decimal("0.00"):
            discrepancies.append(
                DiscrepancyDetail(
                    account_id=acc_id,
                    currency=currency,
                    actual_balance=f"{actual_bal:.2f}",
                    expected_balance=f"{expected_bal:.2f}",
                    drift=f"{drift:+.2f}",
                    reason=(
                        f"Balance drift detected: Cached projection ({actual_bal:.2f}) differs from "
                        f"ledger history (initial {initial_bal:.2f} + credits {total_credits:.2f} "
                        f"- debits {total_debits:.2f} = {expected_bal:.2f}) by {drift:+.2f}"
                    ),
                )
            )

    # -------------------------------------------------------------------------
    # 2. Audit Double-Entry Invariant:
    #    For every transaction: sum(credits) == sum(debits)
    # -------------------------------------------------------------------------
    txn_audit_stmt = (
        select(
            Transaction.id,
            credit_sum,
            debit_sum,
        )
        .outerjoin(LedgerEntry, Transaction.id == LedgerEntry.transaction_id)
        .group_by(Transaction.id)
    )
    txn_rows = (await db.execute(txn_audit_stmt)).all()
    transactions_audited = len(txn_rows)

    for row in txn_rows:
        t_id, t_credits, t_debits = row
        if t_credits != t_debits:
            discrepancies.append(
                DiscrepancyDetail(
                    account_id=t_id,  # references broken transaction UUID
                    currency="N/A",
                    actual_balance=f"{t_credits:.2f}",
                    expected_balance=f"{t_debits:.2f}",
                    drift=f"{t_credits - t_debits:+.2f}",
                    reason=(
                        f"Transaction {t_id} is unbalanced: credits ({t_credits:.2f}) "
                        f"do not equal debits ({t_debits:.2f})"
                    ),
                )
            )

    # -------------------------------------------------------------------------
    # 3. Calculate Metrics and Persist Run
    # -------------------------------------------------------------------------
    elapsed_ms = Decimal(str(round((time.perf_counter() - start_time) * 1000, 2)))
    drifts_detected = len(discrepancies)
    overall_status = "HEALTHY" if drifts_detected == 0 else "DRIFT_DETECTED"

    run_record = ReconciliationRun(
        id=uuid.uuid4(),
        status=overall_status,
        accounts_audited=accounts_audited,
        transactions_audited=transactions_audited,
        drifts_detected=drifts_detected,
        discrepancies=[d.model_dump(mode="json") for d in discrepancies],
        execution_time_ms=elapsed_ms,
    )
    db.add(run_record)
    await db.commit()
    await db.refresh(run_record)

    return ReconciliationResponse(
        reconciliation_id=run_record.id,
        status=run_record.status,
        accounts_audited=run_record.accounts_audited,
        transactions_audited=run_record.transactions_audited,
        drifts_detected=run_record.drifts_detected,
        discrepancies=discrepancies,
        execution_time_ms=f"{run_record.execution_time_ms:.2f}",
        created_at=run_record.created_at,
    )


async def get_reconciliation_status(db: AsyncSession) -> ReconciliationStatusResponse:
    """Fetch the latest reconciliation run and current system health summary."""
    total_runs_stmt = select(func.count(ReconciliationRun.id))
    total_runs = (await db.execute(total_runs_stmt)).scalar() or 0

    latest_run_stmt = (
        select(ReconciliationRun).order_by(ReconciliationRun.created_at.desc()).limit(1)
    )
    latest_run = (await db.execute(latest_run_stmt)).scalar_one_or_none()

    if latest_run is None:
        return ReconciliationStatusResponse(
            system_health="NO_RUNS",
            total_runs=0,
            last_audited_at=None,
            latest_run=None,
        )

    discrepancies = [DiscrepancyDetail.model_validate(d) for d in (latest_run.discrepancies or [])]

    latest_response = ReconciliationResponse(
        reconciliation_id=latest_run.id,
        status=latest_run.status,
        accounts_audited=latest_run.accounts_audited,
        transactions_audited=latest_run.transactions_audited,
        drifts_detected=latest_run.drifts_detected,
        discrepancies=discrepancies,
        execution_time_ms=f"{latest_run.execution_time_ms:.2f}",
        created_at=latest_run.created_at,
    )

    return ReconciliationStatusResponse(
        system_health=latest_run.status,
        total_runs=total_runs,
        last_audited_at=latest_run.created_at,
        latest_run=latest_response,
    )
