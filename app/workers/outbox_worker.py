# CORE LOGIC: understand this file line by line.
"""Asynchronous Transactional Outbox Polling Worker.

Implements the Transactional Outbox Pattern to decouple the high-throughput payment
execution path from slower external AI/LLM operations.

Concurrency Design:
- Uses PostgreSQL 'SELECT ... FOR UPDATE SKIP LOCKED'.
- When multiple outbox workers run in parallel across multiple container instances,
  each worker exclusively locks an independent batch of pending records without blocking
  other workers.
- Guarantees at-least-once delivery with graceful retries and safe fallback.
"""

import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.models.outbox import Outbox
from app.models.transaction import Transaction
from app.services.categorizer import TransactionCategorizer, get_default_categorizer

logger = logging.getLogger(__name__)


async def process_outbox_batch(
    db: AsyncSession,
    categorizer: TransactionCategorizer | None = None,
    batch_size: int = 10,
    transaction_ids: list[uuid.UUID] | None = None,
) -> int:
    """Process a single batch of pending outbox records using FOR UPDATE SKIP LOCKED.

    Args:
        db: Active asynchronous database session.
        categorizer: Categorization engine implementation (defaults to env-based categorizer).
        batch_size: Maximum number of pending records to claim in this batch.
        transaction_ids: Optional list of transaction IDs to restrict processing to.

    Returns:
        Number of outbox records successfully processed.
    """
    if categorizer is None:
        categorizer = get_default_categorizer()

    # 1. Claim batch of pending outbox rows using SKIP LOCKED
    stmt = select(Outbox).where(Outbox.status == "PENDING")
    if transaction_ids:
        stmt = stmt.where(Outbox.transaction_id.in_(transaction_ids))

    stmt = stmt.order_by(Outbox.created_at).limit(batch_size).with_for_update(skip_locked=True)
    result = await db.execute(stmt)
    outbox_entries = list(result.scalars().all())

    if not outbox_entries:
        return 0

    processed_count = 0

    for outbox_entry in outbox_entries:
        outbox_entry.attempts += 1

        try:
            # 2. Fetch associated transaction record
            txn = await db.get(Transaction, outbox_entry.transaction_id)
            if txn is None:
                logger.error(
                    "Outbox entry %s references missing transaction %s",
                    outbox_entry.id,
                    outbox_entry.transaction_id,
                )
                outbox_entry.status = "FAILED"
                continue

            # 3. Categorize transaction memo asynchronously
            category = await categorizer.categorize(txn.memo)
            txn.ai_category = category
            outbox_entry.status = "DONE"
            processed_count += 1
            logger.info("Transaction %s categorized as '%s'", txn.id, category)

        except Exception as err:
            logger.error("Failed processing outbox task %s: %s", outbox_entry.id, err)
            if outbox_entry.attempts >= 3:
                outbox_entry.status = "FAILED"
                txn = await db.get(Transaction, outbox_entry.transaction_id)
                if txn and not txn.ai_category:
                    txn.ai_category = "Uncategorized"

    # 4. Commit updates for this batch atomically
    await db.commit()
    return processed_count


async def run_outbox_worker_loop(
    categorizer: TransactionCategorizer | None = None,
    poll_interval: float | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Continuous background worker loop polling for pending outbox tasks."""
    settings = get_settings()
    interval = poll_interval if poll_interval is not None else settings.outbox_poll_interval_seconds
    if categorizer is None:
        categorizer = get_default_categorizer()

    logger.info("Outbox worker loop started (poll interval: %.2fs)", interval)

    while stop_event is None or not stop_event.is_set():
        try:
            async with AsyncSessionLocal() as session:
                count = await process_outbox_batch(
                    db=session,
                    categorizer=categorizer,
                    batch_size=settings.outbox_batch_size,
                )
                if count > 0:
                    logger.debug("Processed %d outbox tasks", count)
        except Exception as err:
            logger.error("Error in outbox worker loop iteration: %s", err)

        await asyncio.sleep(interval)

    logger.info("Outbox worker loop stopped")
