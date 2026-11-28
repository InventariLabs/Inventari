"""Tables of the rentals module.

A booking is a promise for a window: the borrower, the window, a status and
lines. A line names one asset, or a model and a count that pickup resolves to
assets. A block is time an asset cannot be booked (service, repair); the
buffer rules say how much time around a booking an asset needs to be checked
and packed. Nothing here stores "late": overdue is read from the window and
the status.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.module_sdk import CoreModelBase

BOOKING_STATUSES = ('RESERVED', 'PICKED_UP', 'RETURNED', 'CANCELLED')
LINE_KINDS = ('asset', 'model')
BLOCK_SOURCES = ('MANUAL', 'SERVICE')
CONDITIONS = ('GOOD', 'DAMAGED', 'NEEDS_REPAIR')


class RentalKit(CoreModelBase):
    """A named set of assets or models handed out together.

    A kit is a booking convenience, not a second stock register: a booking
    line that names a kit is stored as one line per member, all carrying the
    kit's id and name, so availability, pickup and return keep working on
    units. The code is what a scanner reads to take the whole set at once.
    """

    __tablename__ = 'rental_kits'
    __table_args__ = (
        Index('uq_rental_kits_org_name', 'organization_id', 'name', unique=True),
        Index('uq_rental_kits_org_code', 'organization_id', 'code', unique=True),
        {'keep_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    members: Mapped[list['RentalKitMember']] = relationship(
        back_populates='kit',
        cascade='all, delete-orphan',
        order_by='RentalKitMember.created_at',
    )


class RentalKitMember(CoreModelBase):
    """One member of a kit: a specific asset, or a model and a count."""

    __tablename__ = 'rental_kit_members'
    __table_args__ = (
        CheckConstraint(
            '(item_id IS NOT NULL AND model IS NULL) '
            'OR (item_id IS NULL AND model IS NOT NULL)',
            name='ck_rental_kit_members_one_kind',
        ),
        CheckConstraint('quantity > 0', name='ck_rental_kit_members_quantity'),
        Index('ix_rental_kit_members_org_kit', 'organization_id', 'kit_id'),
        {'keep_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'), index=True
    )
    kit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('rental_kits.id', ondelete='CASCADE'), index=True
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('items.id', ondelete='CASCADE'), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    kit: Mapped[RentalKit] = relationship(back_populates='members')


class RentalBooking(CoreModelBase):
    """One promise of equipment for a window."""

    __tablename__ = 'rental_bookings'
    __table_args__ = (
        CheckConstraint(
            "status IN ('RESERVED', 'PICKED_UP', 'RETURNED', 'CANCELLED')",
            name='ck_rental_bookings_status',
        ),
        Index(
            'ix_rental_bookings_org_window', 'organization_id', 'starts_at', 'ends_at'
        ),
        Index('ix_rental_bookings_org_status', 'organization_id', 'status'),
        {'keep_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default='RESERVED')

    # The borrower is one of three: a partner, a user of this organization,
    # or somebody outside it with a name and an e-mail. The name is kept on
    # the booking so the row still reads after a partner is removed.
    borrower_partner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('partners.id', ondelete='SET NULL'), nullable=True, index=True
    )
    borrower_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True
    )
    borrower_name: Mapped[str] = mapped_column(String(255))
    borrower_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # When it actually left and came back; the window above is the promise.
    picked_up_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    returned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Reminder markers. The end reminder goes out once per booking; the late
    # one once per organization-local day, so a long loan is nudged daily
    # and no run of the worker mails the same morning twice.
    end_reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    late_reminder_sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    lines: Mapped[list['RentalBookingLine']] = relationship(
        back_populates='booking',
        cascade='all, delete-orphan',
        order_by='RentalBookingLine.created_at',
    )
    units: Mapped[list['RentalBookingUnit']] = relationship(
        back_populates='booking', cascade='all, delete-orphan'
    )

    @property
    def is_late(self) -> bool:
        """Late is read, never stored: a picked-up booking past its end."""
        return self.status == 'PICKED_UP' and self.ends_at < datetime.now(UTC)

    @property
    def held_from(self) -> datetime:
        """When the booking starts holding its units.

        A hand-out made before the window opens takes them from that moment.
        """
        if self.picked_up_at is not None:
            return min(self.starts_at, self.picked_up_at)
        return self.starts_at


class RentalBookingLine(CoreModelBase):
    """A line of a booking: one asset, or a model and a count."""

    __tablename__ = 'rental_booking_lines'
    __table_args__ = (
        CheckConstraint(
            '(item_id IS NOT NULL AND model IS NULL) '
            'OR (item_id IS NULL AND model IS NOT NULL)',
            name='ck_rental_booking_lines_one_kind',
        ),
        CheckConstraint('quantity > 0', name='ck_rental_booking_lines_quantity'),
        Index('ix_rental_booking_lines_org_item', 'organization_id', 'item_id'),
        Index('ix_rental_booking_lines_org_model', 'organization_id', 'model'),
        {'keep_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'), index=True
    )
    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('rental_bookings.id', ondelete='CASCADE'), index=True
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('items.id', ondelete='CASCADE'), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    # The kit this line came from, kept after the kit is deleted so the
    # booking still reads as one set.
    kit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('rental_kits.id', ondelete='SET NULL'), nullable=True
    )
    kit_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    booking: Mapped[RentalBooking] = relationship(back_populates='lines')
    units: Mapped[list['RentalBookingUnit']] = relationship(
        back_populates='line', cascade='all, delete-orphan'
    )

    @property
    def unresolved_count(self) -> int:
        """How many units of a model line pickup has not named yet."""
        return max(0, self.quantity - len(self.units))


class RentalBookingUnit(CoreModelBase):
    """The specific asset a line is (or was) handed out as.

    A specific line has its unit from the start; a model line gets one per
    scan at pickup. The equipment assignment the pickup opened is kept here
    so the return hands back the same hand-out. ``condition`` and
    ``returned_at`` record what came back.
    """

    __tablename__ = 'rental_booking_units'
    __table_args__ = (
        Index('ix_rental_booking_units_org_item', 'organization_id', 'item_id'),
        Index('uq_rental_booking_units_line_item', 'line_id', 'item_id', unique=True),
        {'keep_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'), index=True
    )
    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('rental_bookings.id', ondelete='CASCADE'), index=True
    )
    line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('rental_booking_lines.id', ondelete='CASCADE'), index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('items.id', ondelete='CASCADE'), index=True
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('equipment_assignments.id', ondelete='SET NULL'), nullable=True
    )
    condition: Mapped[str | None] = mapped_column(String(30), nullable=True)
    return_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    booking: Mapped[RentalBooking] = relationship(back_populates='units')
    line: Mapped[RentalBookingLine] = relationship(back_populates='units')


class RentalBlock(CoreModelBase):
    """Time an asset cannot be booked: maintenance, repair, or a manual hold."""

    __tablename__ = 'rental_blocks'
    __table_args__ = (
        CheckConstraint(
            "source IN ('MANUAL', 'SERVICE')", name='ck_rental_blocks_source'
        ),
        CheckConstraint('ends_at > starts_at', name='ck_rental_blocks_window_order'),
        Index(
            'ix_rental_blocks_org_item_window',
            'organization_id',
            'item_id',
            'starts_at',
        ),
        {'keep_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'), index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('items.id', ondelete='CASCADE'), index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default='MANUAL')
    # The return that opened a service block, so the screen can say why.
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('rental_bookings.id', ondelete='SET NULL'), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RentalBufferRule(CoreModelBase):
    """Hours an asset needs before and after a booking, per model or category.

    A rule names either a model or a category, never both: the two are two
    ways to say which assets it covers, and an asset matches the most
    specific rule that names it.
    """

    __tablename__ = 'rental_buffer_rules'
    __table_args__ = (
        CheckConstraint(
            '(model IS NOT NULL) <> (category_id IS NOT NULL)',
            name='ck_rental_buffer_rules_one_target',
        ),
        CheckConstraint(
            'hours_before >= 0 AND hours_after >= 0',
            name='ck_rental_buffer_rules_hours',
        ),
        Index(
            'uq_rental_buffer_rules_org_model',
            'organization_id',
            'model',
            unique=True,
            postgresql_where=text('model IS NOT NULL'),
        ),
        Index(
            'uq_rental_buffer_rules_org_category',
            'organization_id',
            'category_id',
            unique=True,
            postgresql_where=text('category_id IS NOT NULL'),
        ),
        {'keep_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'), index=True
    )
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('categories.id', ondelete='CASCADE'), nullable=True
    )
    hours_before: Mapped[int] = mapped_column(Integer, default=0)
    hours_after: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
