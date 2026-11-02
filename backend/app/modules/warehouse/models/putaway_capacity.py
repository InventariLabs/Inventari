"""Putaway capacity models — how much a shelf holds, per product.

Beside the PutawayRule whose decision they sharpen, in the documents
module: the consumer is the receipt planner (resolver picks the first
location the goods fit), and the company overview reads occupancy from
the same rows. Core stays neutral; a home without this module never
sets a capacity and never sees one.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.module_sdk import CoreModelBase


class PutawayCapacity(CoreModelBase):
    """The most of one product one location holds, in the product's stock unit.

    Unique per (organization, location, product): one shelf, one honest
    number per product. A location with no rows has no limit — the
    org-wide default that keeps every existing organization unchanged.
    """

    __tablename__ = 'putaway_capacity'
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'location_id',
            'product_template_id',
            name='uq_putaway_capacity_org_loc_product',
        ),
        Index('ix_putaway_capacity_org', 'organization_id'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='CASCADE'),
        nullable=False,
    )
    product_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        nullable=False,
    )
    # In the product's stock unit — the unit every stock number for this
    # product already speaks, so the capacity compares against the shelf's
    # quants without a conversion.
    max_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PutawayLocationSetting(CoreModelBase):
    """Whether a location takes a single product only, or a mix.

    Mixed is the default — absent row means mixed — so the flag only
    exists where somebody chose to restrict a shelf. The resolver reads it
    to refuse a product into a shelf that another product already owns.
    """

    __tablename__ = 'putaway_location_settings'
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'location_id',
            name='uq_putaway_location_settings_org_loc',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='CASCADE'),
        nullable=False,
    )
    single_product: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default='false'
    )
