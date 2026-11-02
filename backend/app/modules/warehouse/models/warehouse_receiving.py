"""How a warehouse receives: in one go, or into a receiving area first.

A small shop puts the delivery on the shelf as it unpacks it; a larger
warehouse unloads at the dock and has somebody else carry the goods to the
shelves later. The choice is made per warehouse — a top-level location —
and the absence of a row is the default, one step, so every organization
that never chose keeps receiving exactly as before.

In two steps a receipt lands its goods in the warehouse's receiving area,
a location made inside the warehouse when the mode is first used, and the
goods standing there are the putaway tasks of To do until they are moved.

The same row says whether the warehouse keeps fixed places (the default) or
stores goods wherever there is room (``free_placement``); only the first asks a
worker whether the shelf they used is now a product's home.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.module_sdk import CoreModelBase


class WarehouseReceiving(CoreModelBase):
    """One warehouse's receiving mode and the area two-step receipts land in."""

    __tablename__ = 'document_warehouse_receiving'
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'warehouse_id',
            name='uq_document_warehouse_receiving_org_warehouse',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    #: The top-level location the choice is made for.
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='CASCADE'),
        nullable=False,
    )
    two_step: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default='false'
    )
    #: A warehouse that stores wherever there is room (pallet stores,
    #: logistics): a product has no home shelf there, so put-away never asks
    #: whether to make one. Off by default — a home or a small business keeps
    #: fixed places.
    free_placement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default='false'
    )
    #: Where two-step receipts land. Kept when the mode is switched back, so
    #: goods still waiting there stay tasks; empty once the location is gone,
    #: and made again the next time a receipt needs it.
    receiving_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
