"""WMS pick session and pick line models."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.module_sdk import CoreModelBase


class WmsPickSession(CoreModelBase):
    """Guided picking session over one warehouse document, or several.

    ``document_id`` is the session's first document, and every session has
    one. A picking session started over several dispatches lists all of
    them, the first included, in ``WmsPickSessionDocument``; a session with
    no rows there is the session of its ``document_id`` alone — receiving's,
    and every session written before the list existed.
    """

    __tablename__ = 'wms_pick_sessions'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('documents.id', ondelete='CASCADE'),
        index=True,
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id'),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), default='active')
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When the session was last started, resumed or scanned in; ``None`` on
    #: a session written before the column, which reads ``started_at``.
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    meta_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    lines: Mapped[list[WmsPickLine]] = relationship(
        'WmsPickLine',
        back_populates='session',
        cascade='all, delete-orphan',
        order_by='WmsPickLine.pick_order',
    )


class WmsPickSessionDocument(CoreModelBase):
    """A document picked in a session, in the order the session was asked for.

    The first document stays on ``WmsPickSession.document_id`` as well, so
    every reader that asks a session for its document keeps its answer; what
    the list adds is the others. The lines need no column of their own: each
    names its document line, and the line names its document.
    """

    __tablename__ = 'wms_pick_session_documents'

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('wms_pick_sessions.id', ondelete='CASCADE'),
        primary_key=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('documents.id', ondelete='CASCADE'),
        primary_key=True,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, default=0)


class WmsPickLine(CoreModelBase):
    """Single pick instruction within a session."""

    __tablename__ = 'wms_pick_lines'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('wms_pick_sessions.id', ondelete='CASCADE'),
        index=True,
    )
    document_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('document_lines.id', ondelete='CASCADE'),
        index=True,
    )
    #: The group this line plans from — the shelf's anchor row, one per
    #: (organization, product, shelf) — and, below, the batch it waits for.
    anchor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('stock_anchors.id', ondelete='SET NULL'),
        nullable=True,
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('stock_lots.id', ondelete='SET NULL'),
        nullable=True,
    )
    #: The shelf a picking line is planned from, so a scanned shelf label can
    #: be checked against it. Receiving leaves it empty: its shelf is the
    #: putaway plan, which changes while the session runs.
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'),
        nullable=True,
    )
    pick_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    picked_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    bin_location: Mapped[str | None] = mapped_column(String(255))
    product_name: Mapped[str | None] = mapped_column(String(255))
    lot_name: Mapped[str | None] = mapped_column(String(100))
    #: The date of the stock the line plans to take: its batch's or, with no
    #: batch, the record's own.
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    uom_symbol: Mapped[str | None] = mapped_column(String(10))

    session: Mapped[WmsPickSession] = relationship(
        'WmsPickSession', back_populates='lines'
    )


class WmsPickLineLot(CoreModelBase):
    """What a pick line took from one batch.

    A line picked from several batches (25 where the first holds 20) carries
    one row per batch, so closing the session can write the document one line
    per batch actually taken and the books name the batches that left the
    shelf. A line served by the product's strategy, with no batch named, has
    no rows; its quantity is whatever the strategy draws at completion.
    """

    __tablename__ = 'wms_pick_line_lots'

    pick_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('wms_pick_lines.id', ondelete='CASCADE'),
        primary_key=True,
    )
    lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('stock_lots.id', ondelete='CASCADE'),
        primary_key=True,
        index=True,
    )
    lot_name: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    #: The order the batches were first scanned in, which is the order the
    #: document lines are written in.
    position: Mapped[int] = mapped_column(Integer, default=0)
