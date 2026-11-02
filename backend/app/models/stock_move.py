"""StockMove — explicit WMS stock movement record.

Every change to physical stock creates a StockMove row. This is the
authoritative ledger for analytics (aging, FIFO/FEFO history, lot
traceability, GS1/WMS compliance).

Why not reuse ItemHistory?
  - ItemHistory is a free-text audit log keyed by item_id.
  - ItemHistory does not distinguish receipts from deliveries, has no
    lot/quant granularity, and is not indexed for movement queries.
  - StockMove is a structured record with from/to locations, quantity,
    lot, and completion time — the same primitives any WMS exposes.

The ledger is append-only and every row lands directly at
``state='done'``. There is no draft/confirm workflow above it and no
code transitions the column — it is kept so a future workflow has a
place to stand, not because a machine is running.

The ``state`` and ``reference_type`` vocabularies are contracts
(``app.core.contracts``) re-exported here: a module names their values
without importing this file.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.contracts._stock_dtos import (
    StockMoveReferenceType,
    StockMoveState,
)
from app.database import Base

__all__ = ['StockMove', 'StockMoveReferenceType', 'StockMoveState']


class StockMove(Base):
    """Explicit WMS stock movement record.

    Direction is conveyed by ``from_location_id`` / ``to_location_id``:
      - both set        → internal transfer
      - ``from`` None   → external receipt
      - ``to`` None     → external dispatch
      - both None       → invalid (CHECK constraint enforces ≥1 set)
    """

    __tablename__ = 'stock_moves'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    product_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        index=True,
    )
    from_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'),
        nullable=True,
    )
    to_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'),
        nullable=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('stock_lots.id', ondelete='SET NULL'),
        index=True,
        nullable=True,
    )
    # Whose goods the movement is about — the organization's own when NULL.
    # One rule for every door (docs/subsystems/STOCK.md): the owner comes
    # from the document line, and the movement says whose goods left the
    # same way the reservation row and the quant say whose goods stand.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('partners.id', ondelete='SET NULL'),
        index=True,
        nullable=True,
    )
    # The date of the goods that left, as the draw ranked them: the batch's,
    # or -- for stock with no batch -- the record's own. NULL when undated.
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    state: Mapped[str] = mapped_column(
        String(20), default=StockMoveState.DONE, nullable=False
    )
    reference_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Polymorphic — no FK constraint; target table depends on reference_type.
    reference_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index('ix_stock_moves_org_template', 'organization_id', 'product_template_id'),
        # The ledger's own sort order. The date a movement is *about* is
        # ``completed_at`` falling back to ``created_at``, which is neither
        # column on its own, so no index on either one can serve it: without
        # this one Postgres reads the organization's whole ledger and sorts
        # it in memory to hand back a page of fifty. The trailing id is the
        # tiebreak the list pages on, and DESC has to be written down —
        # a backward scan of the ascending index would order the id the
        # wrong way.
        Index(
            'ix_stock_moves_org_moved_at',
            'organization_id',
            text('coalesce(completed_at, created_at) DESC'),
            'id',
        ),
        Index('ix_stock_moves_from_loc', 'from_location_id'),
        Index('ix_stock_moves_to_loc', 'to_location_id'),
        Index('ix_stock_moves_reference', 'reference_type', 'reference_id'),
        Index('ix_stock_moves_completed_at', 'completed_at'),
        Index('ix_stock_moves_created_at', 'created_at'),
        CheckConstraint('quantity > 0', name='ck_stock_moves_qty_positive'),
        CheckConstraint(
            'from_location_id IS NOT NULL OR to_location_id IS NOT NULL',
            name='ck_stock_moves_at_least_one_location',
        ),
        # Idempotency for the one-time backfill script: rows translated
        # from ItemHistory use (reference_type, reference_id) as a natural
        # key.  New moves from _post_the_change_async have reference_type='item'
        # and are not covered by this index.
        Index(
            'uq_stock_moves_backfill_ref',
            'reference_type',
            'reference_id',
            unique=True,
            postgresql_where=text("reference_type = 'item_history'"),
        ),
    )
