from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StockLedgerTotal(Base):
    """What the movement ledger nets to for one product on one shelf.

    The arrivals at the shelf minus the departures from it, over every done
    movement there ever was. The stock reconciliation compares the shelf with
    this number, and used to add it up from the whole ledger on every pass:
    the ledger only grows, so each pass cost more than the one before, for
    ever.

    Nothing in the application writes this table. Triggers on
    ``stock_moves`` (``ledgertotals01``) move it in the statement that writes
    the movement, so it is never behind the ledger and has no catch-up of its
    own to get wrong; a group whose movements cancel out keeps its row at
    zero. A cascade from the product, the shelf or the organization takes the
    row away together with the movements it summed.
    """

    __tablename__ = 'stock_ledger_totals'

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'), primary_key=True
    )
    product_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        primary_key=True,
        index=True,
    )
    storage_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='CASCADE'),
        primary_key=True,
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
