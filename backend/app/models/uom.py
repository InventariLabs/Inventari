import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UomCategory(Base):
    """
    Category of units, e.g. Weight, Volume, Unit, Length.
    Units can only be converted within the same category.

    organization_id is NULL for system-provided categories,
    set to a specific org UUID for tenant-specific categories.
    """

    __tablename__ = 'uom_categories'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(50))

    uoms: Mapped[list['Uom']] = relationship(back_populates='category')

    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'name',
            name='uq_uom_category_org_name',
        ),
    )


class Uom(Base):
    """
    Unit of Measure, e.g. kg, g, lb, oz.

    organization_id is NULL for system-provided units,
    set to a specific org UUID for tenant-specific units.
    """

    __tablename__ = 'uoms'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
        nullable=True,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('uom_categories.id'))
    name: Mapped[str] = mapped_column(String(50))
    symbol: Mapped[str] = mapped_column(String(10))

    #: How many reference units one of this unit is. A definition, not a
    #: measurement, so it is exact: as ``double precision`` every SQL
    #: expression that multiplied a stored quantity by it left ``numeric``
    #: and finished the sum in binary floating point.
    #:
    #: Eighteen digits with nine after the point covers the range a unit
    #: table needs — 3785.41 for a US gallon in millilitres at one end,
    #: 0.001 for a milligram in grams at the other — with room for a
    #: conversion somebody defines by hand.
    factor: Mapped[Decimal] = mapped_column(Numeric(18, 9), default=Decimal('1'))
    is_reference: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    #: The smallest step this unit is counted in — 1 for pieces, 0.001 for
    #: grams. Exact for the same reason as ``factor``: it is compared against
    #: quantities that are ``numeric``.
    rounding: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal('0.01'))

    category: Mapped['UomCategory'] = relationship(
        back_populates='uoms', lazy='selectin'
    )

    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'name',
            name='uq_uom_org_name',
        ),
        # One reference unit per category: every conversion in the category
        # is a factor against it.
        Index(
            'uq_uom_category_reference',
            'category_id',
            unique=True,
            postgresql_where=text('is_reference = true'),
        ),
    )
