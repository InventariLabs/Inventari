import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class WebhookEndpoint(Base):
    """Outbound webhook endpoint configured per organization."""

    __tablename__ = 'webhook_endpoints'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )

    # Configuration
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(2048))
    secret: Mapped[str | None] = mapped_column(
        String(512)
    )  # Fernet-encrypted, stored as 'enc:...'
    http_method: Mapped[str] = mapped_column(String(10), default='POST')

    # Event filtering — JSONB array, e.g. ["item.used", "item.created"]
    event_types: Mapped[list[str]] = mapped_column(JSONB, default=list)

    # Retry policy
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    retry_backoff_seconds: Mapped[int] = mapped_column(Integer, default=10)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10)

    # Status
    is_active: Mapped[bool] = mapped_column(default=True)

    # Denormalized stats for quick dashboard view
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    #: When the circuit breaker switched this endpoint off — and nothing else.
    #: An administrator pausing an endpoint leaves it NULL, which is the whole
    #: point: the card used to read "auto-disabled" off ``is_active`` alone and
    #: sent people looking for deliveries that never failed. Recorded rather
    #: than derived from ``consecutive_failures >= threshold``, because the
    #: threshold is a setting an administrator may raise afterwards, and what
    #: happened does not change when the rule for it does.
    auto_disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    delivery_logs: Mapped[list['WebhookDeliveryLog']] = relationship(
        back_populates='webhook_endpoint',
        cascade='all, delete-orphan',
        lazy='dynamic',
    )


class WebhookDeliveryLog(Base):
    """Audit log for every outbound webhook delivery attempt."""

    __tablename__ = 'webhook_delivery_logs'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    webhook_endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('webhook_endpoints.id', ondelete='CASCADE'),
        index=True,
    )
    # Denormalized for efficient tenant-scoped queries
    organization_id: Mapped[uuid.UUID] = mapped_column(index=True)

    event_type: Mapped[str] = mapped_column(String(100))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB)

    # Response
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[str | None] = mapped_column(Text)  # Truncated to 1 KB
    error_message: Mapped[str | None] = mapped_column(Text)

    # The receiver-facing identity of this delivery (event × endpoint):
    # minted once with the row, sent in the X-Inventari-Delivery header and
    # in the payload body on every attempt, so retries dedup instead of
    # arriving as new events and the history can be matched against a
    # receiver's log. NULL only on rows written before the field existed.
    delivery_id: Mapped[str | None] = mapped_column(String(36))

    # Why the application itself stopped trying, when it did:
    # 'circuit_breaker' | 'webhook_disabled' | 'webhook_deleted' |
    # 'module_disabled'. Set only when nobody answered — a receiver's
    # status code is the receiver's answer, and this row must not dress
    # our own refusal in their clothes.
    abandon_reason: Mapped[str | None] = mapped_column(String(40))

    # The moment the attempt that produced the row's current status ended.
    # created_at is the enqueue time and drifts away from the outcome by
    # the whole backoff; the history shows this one when it has it.
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Retry tracking
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Claim timestamp for the retry worker's claim-then-deliver protocol:
    # set while a worker owns the row for an in-flight HTTP attempt.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # "success" | "pending_retry" | "retrying" | "failed"
    delivery_status: Mapped[str] = mapped_column(String(20))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    webhook_endpoint: Mapped['WebhookEndpoint'] = relationship(
        back_populates='delivery_logs'
    )
