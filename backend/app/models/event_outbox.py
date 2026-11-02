import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class EventOutbox(Base):
    """Transactional outbox for durable event emission.

    ``event_bus.emit_transactional`` writes a row here in the SAME database
    transaction as the business operation; the outbox relay publishes it to
    the Redis event stream after commit. A crash between commit and publish
    can no longer lose the event.
    """

    __tablename__ = 'event_outbox'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Nullable: non-tenant events have no owning organization.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    event: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    #: The module that emitted the event, when a module did (None for core
    #: code). The relay copies it onto the stream message so a handler that
    #: fails can be attributed to the module it belongs to, not just to the
    #: node that relayed it.
    emitter_module: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
