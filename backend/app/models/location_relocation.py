"""LocationRelocation — a location that physically moved, with its stock.

A storage location keeps its id when it moves in the tree, so the movements
of the products inside cannot say by their two ends that anything happened:
both ends are the same shelf. The relocation is the document they point at
(``StockMove.reference_type = 'location_relocation'``): which location moved,
the path it left and the path it reached, and when.

The paths are written as they read at the move, the way the journal records
what a record was called when the change was made — a parent renamed or
deleted later does not rewrite what the history says. ``from_parent_id`` is
what the stock on a past date reads to put a relocated subtree back where it
stood (``stock_as_of_service``).

A move that only corrects the layout writes none of this: the stock was
always where the tree now puts it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LocationRelocation(Base):
    __tablename__ = 'location_relocations'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'), nullable=True
    )
    location_name: Mapped[str] = mapped_column(String(255), nullable=False)
    from_parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'), nullable=True
    )
    to_parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'), nullable=True
    )
    # NULL for the top level, which has no path of its own.
    from_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    moved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )

    __table_args__ = (
        Index('ix_location_relocations_org_moved_at', 'organization_id', 'moved_at'),
    )
