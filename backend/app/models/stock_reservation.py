"""Per-document stock reservation tracking.

Each row is one document's hold on one grain of stock: the group's anchor
(a product on a shelf), the batch and the owner, and how much. What a grain
has promised is the sum of its rows, and the records' view reads it that
way; releasing a document's hold deletes that document's rows and touches
no other document's.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StockReservation(Base):
    """Per-document stock reservation record."""

    __tablename__ = 'stock_reservations'
    __table_args__ = (
        Index('ix_reservation_document', 'document_id'),
        Index('ix_reservation_org_doc', 'organization_id', 'document_id'),
        Index('ix_reservation_anchor', 'anchor_id'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
        nullable=False,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    document_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('document_lines.id', ondelete='SET NULL'),
        nullable=True,
    )
    # The grain the row holds: its group's anchor, its batch and its owner.
    anchor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('stock_anchors.id', ondelete='CASCADE'),
        nullable=False,
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('stock_lots.id', ondelete='SET NULL'),
        nullable=True,
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('partners.id', ondelete='SET NULL'),
        nullable=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
