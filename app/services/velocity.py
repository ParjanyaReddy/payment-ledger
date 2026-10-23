# CORE LOGIC: understand this file line by line.
"""Velocity Fraud Detection and Rate Limiting Service.

Enforces financial anti-fraud rules by monitoring transaction frequency and
cumulative monetary volume over rolling time windows. Protects against:
1. Rapid-fire automated card testing / credential stuffing attacks.
2. Sudden account draining / large out-of-pattern volume spikes.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.card import CardAuthorization
from app.models.transaction import Transaction
from app.services.exceptions import VelocityLimitExceededError


async def check_velocity_limits(
    db: AsyncSession,
    account_id: uuid.UUID,
    requested_amount: Decimal,
    include_authorizations: bool = True,
) -> None:
    """Verify that an account has not exceeded frequency or volume velocity fraud rules.

    Args:
        db: Active asynchronous database session.
        account_id: Source account UUID initiating the payment or authorization.
        requested_amount: Decimal monetary amount of the requested transaction.
        include_authorizations: If True, include recent card authorizations in velocity counts.

    Raises:
        VelocityLimitExceededError: If frequency or cumulative volume limits are breached.
    """
    settings = get_settings()
    now = datetime.now(UTC)

    # -------------------------------------------------------------------------
    # 1. Frequency Check: Max N transactions/authorizations in rolling M seconds
    # -------------------------------------------------------------------------
    window_start = now - timedelta(seconds=settings.velocity_window_seconds)

    # Count recent outgoing transactions
    tx_count_stmt = (
        select(func.count(Transaction.id))
        .where(Transaction.from_account_id == account_id)
        .where(Transaction.created_at >= window_start)
    )
    recent_tx_count = (await db.scalar(tx_count_stmt)) or 0

    recent_auth_count = 0
    if include_authorizations:
        # Count recent card authorizations
        auth_count_stmt = (
            select(func.count(CardAuthorization.id))
            .where(CardAuthorization.account_id == account_id)
            .where(CardAuthorization.created_at >= window_start)
        )
        recent_auth_count = (await db.scalar(auth_count_stmt)) or 0

    total_activity_count = recent_tx_count + recent_auth_count
    if total_activity_count >= settings.velocity_max_tx_per_window:
        raise VelocityLimitExceededError(
            account_id=account_id,
            reason=(
                f"Transaction frequency limit exceeded: {total_activity_count} activities "
                f"in the last {settings.velocity_window_seconds}s (limit: {settings.velocity_max_tx_per_window})"
            ),
        )

    # -------------------------------------------------------------------------
    # 2. Cumulative Volume Check: Max daily volume limit in rolling 24 hours
    # -------------------------------------------------------------------------
    daily_window_start = now - timedelta(seconds=settings.velocity_daily_window_seconds)
    max_daily_volume = Decimal(settings.velocity_max_daily_volume)

    tx_volume_stmt = (
        select(func.coalesce(func.sum(Transaction.amount), Decimal("0.00")))
        .where(Transaction.from_account_id == account_id)
        .where(Transaction.created_at >= daily_window_start)
        .where(Transaction.status == "COMPLETED")
    )
    daily_tx_volume = (await db.scalar(tx_volume_stmt)) or Decimal("0.00")

    projected_volume = daily_tx_volume + requested_amount
    if projected_volume > max_daily_volume:
        raise VelocityLimitExceededError(
            account_id=account_id,
            reason=(
                f"Daily transaction volume limit exceeded: current {daily_tx_volume:.2f} + requested "
                f"{requested_amount:.2f} = {projected_volume:.2f} exceeds limit {max_daily_volume:.2f}"
            ),
        )
