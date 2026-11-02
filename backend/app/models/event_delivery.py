import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class EventDelivery(Base):
    """One event handler that failed, and what became of it.

    The bus writes a row the first time a handler raises (or outlasts its
    bound) on a stream delivery, instead of acknowledging the event and
    forgetting it. The retry worker re-runs that handler alone — not the
    event's other handlers, which already did their work — with backoff,
    until it succeeds (``succeeded``) or runs out of attempts (``dead``:
    the dead-letter queue, and an alert to the organization's admins).

    ``(event_id, handler)`` is unique: a redelivered event finds the row
    and leaves the handler to the worker rather than running it twice.
    Handlers that succeed first time leave no row.
    """

    __tablename__ = 'event_deliveries'
    __table_args__ = (
        UniqueConstraint(
            'event_id', 'handler', name='uq_event_deliveries_event_handler'
        ),
        # The worker's poll: what is due, oldest first.
        Index('ix_event_deliveries_status_next_attempt', 'status', 'next_attempt_at'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: The event's identity across redeliveries: the outbox row id for a
    #: transactional emit, a fresh id for a plain one.
    event_id: Mapped[str] = mapped_column(String(64))
    event: Mapped[str] = mapped_column(String(100))
    #: ``module.qualname`` of the subscribed function.
    handler: Mapped[str] = mapped_column(String(255))
    # Nullable: non-tenant events have no owning organization.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    #: ``retrying`` → ``succeeded`` | ``dead``.
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
