from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StockAnchor(Base):
    """The row a change to one group of stock locks: a product on a shelf.

    It carries no quantity. Stock is counted on the records, and a record
    exists per batch and owner, so none is a row a writer can lock for the
    whole group — and a group nobody has stocked yet has no row at all. Two
    first receipts to an empty shelf therefore had nothing to wait on. The
    anchor is that row: ``core_api.stock.lock_async`` creates the anchors of
    the keys it is given and locks them, so every write to a group, the first
    one included, waits for the one before it.

    Anchors are never deleted by the code; a group that once had stock keeps
    its row, and only a cascade from the product, the shelf or the
    organization removes it.
    """

    __tablename__ = 'stock_anchors'
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'product_template_id',
            'storage_location_id',
            name='uq_stock_anchor_group',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
    )
    product_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        index=True,
    )
    storage_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='CASCADE'),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
