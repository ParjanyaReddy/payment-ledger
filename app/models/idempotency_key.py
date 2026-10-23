"""IdempotencyKey SQLAlchemy ORM Model.

Stores idempotency keys, request payload hashes, and cached responses
to prevent duplicate charges and race conditions under concurrent submissions.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IdempotencyKey(Base):
    """Idempotency key model storing request hashes and cached response bodies."""

    __tablename__ = "idempotency_keys"

    key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    request_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="IN_PROGRESS",
    )
    response_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    response_body: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('IN_PROGRESS', 'COMPLETED')",
            name="check_idempotency_key_status_valid",
        ),
    )

    def __repr__(self) -> str:
        return f"<IdempotencyKey key={self.key} status={self.status}>"
