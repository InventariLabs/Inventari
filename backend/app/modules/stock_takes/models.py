import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.database import Base
from app.schemas.validators import QUANTITY_MAX_DIGITS, QUANTITY_SCALE

if TYPE_CHECKING:
    from app.models.item import Item
    from app.models.organization import Organization
    from app.models.storage_location import StorageLocation
    from app.models.user import User


class StockTakeDiscrepancyCode(StrEnum):
    """Why a counted quantity differs from what the system held.

    Free text answers "what happened on this shelf" and nothing else. It
    cannot answer the question a warehouse asks after every count — how much
    of the loss is breakage, how much is theft, how much is somebody putting
    the goods on the wrong shelf — because twenty spellings of "broken" do
    not add up. So the difference carries a code from this list, and a note
    for what the list cannot say.

    The vocabulary is the one warehouse systems settled on for shrink
    categories: damage, expiry, loss, a miscount, goods found in the wrong
    place, a unit that was read wrong, and a movement that never reached the
    records. OTHER is the escape hatch, and the note stops being optional
    whenever it is chosen — otherwise the escape hatch is the answer nobody
    can read.
    """

    DAMAGE = 'DAMAGE'
    EXPIRED = 'EXPIRED'
    LOSS = 'LOSS'
    MISCOUNT = 'MISCOUNT'
    WRONG_LOCATION = 'WRONG_LOCATION'
    WRONG_UNIT = 'WRONG_UNIT'
    SYSTEM_ERROR = 'SYSTEM_ERROR'
    OTHER = 'OTHER'


#: The code whose note is not optional — see StockTakeDiscrepancyCode.
FREE_TEXT_DISCREPANCY_CODE = StockTakeDiscrepancyCode.OTHER


class StockTakeStatus(StrEnum):
    """Inventory status."""

    DRAFT = 'draft'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'


class StockTake(Base):
    """
    Inventory session for a specific storage location.
    Represents a single inventory (e.g. "Freezer inventory - January 2026").
    """

    __tablename__ = 'stock_takes'
    __table_args__ = {'extend_existing': True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE')
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE')
    )
    storage_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='CASCADE')
    )
    #: The name the API and the contract DTOs give this column: a client
    #: meets a location, the table keeps its storage_location spelling.
    location_id: Mapped[uuid.UUID] = synonym('storage_location_id')

    name: Mapped[str] = mapped_column(
        String(255)
    )  # e.g. "Freezer inventory - January 2026"
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[StockTakeStatus] = mapped_column(
        Enum(
            StockTakeStatus,
            values_callable=lambda x: [e.value for e in x],
            native_enum=False,
            length=20,
            create_constraint=True,
            name='ck_stock_takes_status',
        ),
        default=StockTakeStatus.DRAFT,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    notes: Mapped[str | None] = mapped_column(Text)  # general inventory notes
    blind_mode: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # hide system_quantity during counting
    require_full_count: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )  # require all items counted before finalize
    tolerance_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )  # ignore differences up to this percent
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The recurring schedule that generated this count, when one did: how To do
    # tells a due count that is under way, or finished today, from one not begun.
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('cycle_count_schedules.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    # The stock adjustment closing this count wrote to the documents register,
    # when it changed anything and that module is on. A plain id: the
    # document is another module's, and the count must not depend on it.
    adjustment_document_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    user: Mapped['User'] = relationship(back_populates='stock_takes')
    organization: Mapped['Organization'] = relationship()
    storage_location: Mapped['StorageLocation'] = relationship(
        back_populates='stock_takes'
    )
    items: Mapped[list['StockTakeItem']] = relationship(
        'app.modules.stock_takes.models.StockTakeItem',
        back_populates='stock_take',
        cascade='all, delete-orphan',
        order_by='app.modules.stock_takes.models.StockTakeItem.item_name',
        lazy='selectin',
    )

    @property
    def items_count(self) -> int:
        return len(self.items)

    @property
    def counted_items_count(self) -> int:
        return sum(1 for item in self.items if item.counted_quantity is not None)

    @property
    def discrepancies_count(self) -> int:
        return sum(1 for item in self.items if item.is_discrepancy == 1)


class StockTakeItem(Base):
    """
    Single item in inventory.
    Stores actual count (counted_quantity) and compares with system (system_quantity).
    """

    __tablename__ = 'stock_take_items'
    __table_args__ = {'extend_existing': True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    stock_take_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('stock_takes.id', ondelete='CASCADE')
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('items.id', ondelete='SET NULL')
    )  # nullable for unknown products; SET NULL keeps counting evidence

    item_name: Mapped[str] = mapped_column(
        String(255)
    )  # denormalization for speed and unknown products
    item_brand: Mapped[str | None] = mapped_column(String(255))
    uom_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('uoms.id'), nullable=True
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id'), nullable=True
    )  # counter assigned to this item
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('stock_lots.id'), nullable=True
    )  # lot tracked during counting

    # The snapshot of items.quantity, so it carries the width that column
    # carries: a narrower row could not hold what the shelf held, and opening
    # a count anywhere near 9,999,999.999 of something answered 500 on the
    # INSERT instead of a stock take.
    system_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(QUANTITY_MAX_DIGITS, QUANTITY_SCALE)
    )  # system quantity before inventory
    counted_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3)
    )  # quantity counted during inventory

    #: The shelf this row counts: where its record stood when the count
    #: opened, or the shelf a counter scanned and found the goods on. The
    #: count walks a tree shelf by shelf, and a quantity is only a statement
    #: about the shelf it was counted on — free text beside it could not say
    #: which one that was.
    storage_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'), nullable=True
    )
    #: Where the row's record stands, on a row counted somewhere else: a unit
    #: that owns its identity (a serial number, or no product card) cannot be
    #: split into a record per shelf, so its one row moves to the shelf it was
    #: found on and remembers this one. Closing the count moves the record
    #: there, and the report shows the shortage here beside the surplus there.
    #: Empty on every row counted where its record stands.
    expected_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'), nullable=True
    )
    location_in_storage: Mapped[str | None] = mapped_column(
        String(255)
    )  # the shelf's code or path, as the counter reads it
    #: The names the API gives these two columns: the shelf a client meets
    #: is a location, and the code read off it its shelf location, as on a
    #: record.
    location_id: Mapped[uuid.UUID | None] = synonym('storage_location_id')
    shelf_location: Mapped[str | None] = synonym('location_in_storage')
    notes: Mapped[str | None] = mapped_column(Text)  # item notes

    recount_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # sent back to be counted again; blocks finalize until it is
    discrepancy_reason_code: Mapped[str | None] = mapped_column(
        String(50)
    )  # a StockTakeDiscrepancyCode — countable across counts
    discrepancy_reason: Mapped[str | None] = mapped_column(
        String(255)
    )  # the note beside the code; required when the code is OTHER
    is_discrepancy: Mapped[int] = mapped_column(
        Integer, default=0
    )  # 0 = no discrepancy, 1 = discrepancy detected

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    stock_take: Mapped['StockTake'] = relationship(
        'app.modules.stock_takes.models.StockTake', back_populates='items'
    )
    item: Mapped['Item'] = relationship(back_populates='stock_take_items')

    @property
    def difference(self) -> 'Decimal | None':
        """Difference between counted and system quantity."""
        if self.counted_quantity is not None and self.system_quantity is not None:
            return self.counted_quantity - self.system_quantity
        return None

    counts: Mapped[list['StockTakeCount']] = relationship(
        'app.modules.stock_takes.models.StockTakeCount',
        back_populates='stock_take_item',
        cascade='all, delete-orphan',
        order_by='StockTakeCount.sequence',
        lazy='selectin',
    )

    uom = relationship('Uom', lazy='joined', foreign_keys=[uom_id])
    assignee = relationship('User', lazy='joined', foreign_keys=[assignee_id])
    lot = relationship('StockLot', lazy='joined', foreign_keys=[lot_id])


class StockTakeCount(Base):
    """One pass of counting over one row.

    A recount does not overwrite the first number. Two people walking the
    same shelf and arriving at the same figure is what makes a correction
    believable, and a disagreement between them is information of its own —
    somebody counted under pressure, or two people read a different shelf.
    Overwritten, both facts are gone and the row says only what the last
    person thought.

    A pass per row rather than two columns, because that is what the systems
    our users arrive from do: SAP raises a fresh physical inventory document
    for a recount and keeps the original, Dynamics hangs many recordings off
    one inventory order and compares them. A third pass is a real thing that
    happens when the first two disagree.
    """

    __tablename__ = 'stock_take_counts'
    __table_args__ = {'extend_existing': True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    stock_take_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('stock_take_items.id', ondelete='CASCADE'), index=True
    )
    #: 1 for the first pass, 2 for the recount, and so on.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    counted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL')
    )
    counted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    stock_take_item: Mapped['StockTakeItem'] = relationship(
        'app.modules.stock_takes.models.StockTakeItem', back_populates='counts'
    )
    counter = relationship('User', lazy='joined', foreign_keys=[counted_by])


class StockTakeClosedLocation(Base):
    """A shelf the counter closed: done with it, whatever it held.

    Closing counts every row of the shelf nobody counted as none, so a shelf
    whose goods are gone is one statement and not a zero typed per row. A
    shelf found empty leaves this row as the trace that somebody looked —
    a count result as much as any number. Rows on a shelf nobody closed are
    left waiting, as they always were.
    """

    __tablename__ = 'stock_take_closed_locations'
    __table_args__ = (
        UniqueConstraint(
            'stock_take_id',
            'storage_location_id',
            name='uq_stock_take_closed_locations_location',
        ),
        {'extend_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    stock_take_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('stock_takes.id', ondelete='CASCADE'), index=True
    )
    storage_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'), nullable=True
    )
    #: The name the API and the contract DTOs give this column: a client
    #: meets a location, the table keeps its storage_location spelling.
    location_id: Mapped[uuid.UUID | None] = synonym('storage_location_id')
    #: The shelf's path when it was closed: the report outlives the tree.
    path: Mapped[str] = mapped_column(Text, nullable=False)
    #: Nothing was on it: no row, or every row counted as none.
    empty: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL')
    )
    closed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    closer: Mapped['User | None'] = relationship(
        'User', lazy='joined', foreign_keys=[closed_by]
    )

    @property
    def closed_by_name(self) -> str | None:
        if self.closer is None:
            return None
        return self.closer.full_name or self.closer.email


class CycleCountFrequency(StrEnum):
    DAILY = 'daily'
    WEEKLY = 'weekly'
    MONTHLY = 'monthly'
    QUARTERLY = 'quarterly'


class CycleCountScope(StrEnum):
    ALL = 'all'
    ZONE = 'zone'
    CATEGORY = 'category'


class CycleCountSchedule(Base):
    """Recurring schedule for partial inventory counts."""

    __tablename__ = 'cycle_count_schedules'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    # The module's enum rule (see backend/AGENTS.md): the column is text with
    # a CHECK over the StrEnum VALUES — never a native PostgreSQL enum type.
    frequency: Mapped[CycleCountFrequency] = mapped_column(
        Enum(
            CycleCountFrequency,
            values_callable=lambda x: [e.value for e in x],
            native_enum=False,
            length=20,
            create_constraint=True,
            name='ck_cycle_count_schedules_frequency',
        ),
        default=CycleCountFrequency.MONTHLY,
    )
    scope: Mapped[CycleCountScope] = mapped_column(
        Enum(
            CycleCountScope,
            values_callable=lambda x: [e.value for e in x],
            native_enum=False,
            length=20,
            create_constraint=True,
            name='ck_cycle_count_schedules_scope',
        ),
        default=CycleCountScope.ALL,
    )
    scope_filter: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tolerance_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE')
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    organization = relationship('Organization')
    creator = relationship('User', foreign_keys=[created_by])
