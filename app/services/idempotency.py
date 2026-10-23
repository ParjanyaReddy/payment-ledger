# CORE LOGIC: understand this file line by line.
"""Race-Safe Idempotency Service for Financial APIs.

Prevents double-charging when clients retry timed-out requests or submit
concurrent duplicate clicks. Enforces:
1. Header-based idempotency key tracking with SHA-256 payload hashing.
2. Atomic INSERT ... ON CONFLICT DO NOTHING claim inside the same DB transaction.
3. Conflict resolution:
   - Differing request payload hash -> 422 Unprocessable Content.
   - In-progress request -> polls briefly, returns 409 Conflict if still processing.
   - Completed request -> replays cached HTTP response code and body.
4. Expiration cleanup for keys older than 24 hours.
"""

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idempotency_key import IdempotencyKey
from app.services.exceptions import LedgerError


class IdempotencyError(LedgerError):
    """Base exception for idempotency violations."""

    pass


class IdempotencyHashMismatchError(IdempotencyError):
    """Raised when an idempotency key is reused with a different request payload."""

    def __init__(self, key: uuid.UUID) -> None:
        self.key = key
        super().__init__(
            f"Idempotency key '{key}' was already used with a different request payload"
        )


class IdempotencyConflictError(IdempotencyError):
    """Raised when a concurrent request with the same key is still processing."""

    def __init__(self, key: uuid.UUID) -> None:
        self.key = key
        super().__init__(
            f"A request with idempotency key '{key}' is currently in progress. Please retry shortly."
        )


def compute_request_hash(method: str, path: str, body: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 hash of HTTP method, endpoint path, and JSON body.

    Sorting JSON keys ensures that payload formatting differences (whitespace, key ordering)
    produce the exact same hash for identical semantic payloads.
    """
    normalized_json = json.dumps(body, sort_keys=True, separators=(",", ":"))
    raw_payload = f"{method.upper()}:{path.rstrip('/')}:{normalized_json}"
    return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()


class IdempotencyClaim:
    """Result of an idempotency claim attempt."""

    def __init__(
        self,
        is_new: bool,
        cached_status_code: int | None = None,
        cached_body: dict[str, Any] | None = None,
    ) -> None:
        self.is_new = is_new
        self.cached_status_code = cached_status_code
        self.cached_body = cached_body


async def claim_or_get_idempotency(
    db: AsyncSession,
    key: uuid.UUID,
    request_hash: str,
    max_wait_seconds: float = 3.0,
    poll_interval: float = 0.05,
) -> IdempotencyClaim:
    """Atomically claim an idempotency key or retrieve the cached response.

    Race-Condition Prevention:
    A naive "SELECT then INSERT" pattern has a race window where two simultaneous
    requests both see "key does not exist".
    Instead, we perform:
        INSERT INTO idempotency_keys (key, request_hash, status)
        VALUES (...) ON CONFLICT (key) DO NOTHING
        RETURNING key;

    If the INSERT returns a row, this transaction owns the key.
    If the INSERT returns nothing, a conflict occurred. We then inspect the existing row:
    - If request_hash differs -> 422 Unprocessable Content.
    - If status == COMPLETED -> Replay cached response body.
    - If status == IN_PROGRESS -> Poll briefly for completion. If still busy, return 409.

    Args:
        db: Active asynchronous SQLAlchemy session.
        key: Unique idempotency UUID from request header.
        request_hash: Deterministic SHA-256 hash of method, path, and payload.
        max_wait_seconds: Maximum time to wait for an in-flight request to finish.
        poll_interval: Polling frequency in seconds.

    Returns:
        IdempotencyClaim indicating if the caller owns the key or should replay a cached response.
    """
    # 1. Attempt atomic insert
    stmt = (
        pg_insert(IdempotencyKey)
        .values(
            key=key,
            request_hash=request_hash,
            status="IN_PROGRESS",
        )
        .on_conflict_do_nothing(index_elements=["key"])
        .returning(IdempotencyKey.key)
    )
    result = await db.execute(stmt)
    inserted_key = result.scalar_one_or_none()

    if inserted_key is not None:
        # We won the race and own the key
        return IdempotencyClaim(is_new=True)

    # 2. Conflict occurred: read existing row and handle replay or wait
    elapsed = 0.0
    while elapsed <= max_wait_seconds:
        # Refresh session cache to view committed updates from concurrent transactions
        query = (
            select(IdempotencyKey)
            .where(IdempotencyKey.key == key)
            .execution_options(populate_existing=True)
        )
        record = (await db.execute(query)).scalar_one_or_none()

        if record is None:
            # Row was rolled back by earlier transaction; re-attempt claim
            return await claim_or_get_idempotency(
                db=db,
                key=key,
                request_hash=request_hash,
                max_wait_seconds=max(0.0, max_wait_seconds - elapsed),
            )

        # Verify payload integrity
        if record.request_hash != request_hash:
            raise IdempotencyHashMismatchError(key=key)

        # If completed, return cached response for immediate replay
        if record.status == "COMPLETED":
            return IdempotencyClaim(
                is_new=False,
                cached_status_code=record.response_code,
                cached_body=record.response_body,
            )

        # If in progress, wait briefly and poll again
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    # If wait timed out while still in progress, signal concurrent conflict
    raise IdempotencyConflictError(key=key)


async def save_idempotency_response(
    db: AsyncSession,
    key: uuid.UUID,
    response_code: int,
    response_body: dict[str, Any],
) -> None:
    """Store the completed HTTP response code and body for subsequent replays."""
    record = await db.get(IdempotencyKey, key)
    if record:
        record.status = "COMPLETED"
        record.response_code = response_code
        record.response_body = response_body
        await db.flush()


async def cleanup_expired_keys(
    db: AsyncSession,
    retention_hours: int = 24,
) -> int:
    """Delete idempotency records older than retention threshold.

    Returns:
        Number of expired keys removed.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=retention_hours)
    stmt = delete(IdempotencyKey).where(IdempotencyKey.created_at < cutoff)
    result = await db.execute(stmt)
    return int(getattr(result, "rowcount", 0))
