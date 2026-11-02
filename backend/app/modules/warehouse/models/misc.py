"""DocumentRelation and InventoryPeriod models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.module_sdk import CoreModelBase


class DocumentRelation(CoreModelBase):
    """Tracks relationships between documents (corrections, splits, fulfillments)."""

    __tablename__ = 'document_relations'
    __table_args__ = (
        Index('ix_doc_relation_source', 'source_document_id'),
        Index('ix_doc_relation_target', 'target_document_id'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('documents.id', ondelete='CASCADE'),
        nullable=False,
    )
    target_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('documents.id', ondelete='CASCADE'),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InventoryPeriod(CoreModelBase):
    """Inventory period closure for month-end document locking."""

    __tablename__ = 'inventory_periods'
    __table_args__ = (
        # one period row per (org, year, month). Previously uniqueness
        # relied only on an advisory lock, so a race or a bypassed code path could
        # create duplicate closure rows.
        UniqueConstraint(
            'organization_id',
            'year',
            'month',
            name='uq_inventory_period_org_year_month',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    reopened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reopened_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExtraCostKind(StrEnum):
    """What the extra invoice was for.

    Countable, unlike a note. The four cover what a small importer actually
    receives; anything else is OTHER with a note beside it.
    """

    FREIGHT = 'freight'
    DUTY = 'duty'
    INSURANCE = 'insurance'
    OTHER = 'other'


class ExtraCostAllocation(StrEnum):
    """How one invoice is spread over the goods it arrived with.

    ``VALUE`` is the default because a shipment is usually charged in
    proportion to what it is worth; ``WEIGHT`` is what a haulier actually
    bills for; ``QUANTITY`` is the fallback that works when nobody typed a
    price — such a line has an unknown cost basis, and a share of a total of
    zero is a division by zero, not a cost.
    """

    VALUE = 'value'
    QUANTITY = 'quantity'
    WEIGHT = 'weight'


class DocumentExtraCost(CoreModelBase):
    """Freight, duty or insurance that belongs in the value of a receipt.

    Without these the shelf is worth what the supplier invoiced and nothing
    else, so every margin computed from it is wrong by the cost of getting
    the goods there — the single most common reason a warehouse's stock value
    disagrees with its accounts.

    Accepted only while the receipt is unposted. Once the layers are written
    the goods may already have left, and there is nothing left to charge:
    spreading the invoice over what remains needs a general ledger to absorb
    the rest, and this product deliberately has none.
    """

    __tablename__ = 'document_extra_costs'
    __table_args__ = (
        Index('ix_document_extra_costs_document', 'document_id'),
        CheckConstraint('amount > 0', name='ck_document_extra_costs_amount'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('documents.id', ondelete='CASCADE'),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    #: NULL means the document's own currency. A cost in any other currency
    #: is refused rather than converted at a rate nobody recorded.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    allocation_method: Mapped[str] = mapped_column(
        String(10), nullable=False, default=ExtraCostAllocation.VALUE
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )


class DocumentNumberSequence(CoreModelBase):
    """The counter behind one numbering prefix, which only ever goes up.

    The next number used to be derived by scanning the numbers already taken
    and adding one to the highest. That reads the register as if it were the
    counter, and the register forgets: a draft deleted the same afternoon
    dropped out of the scan and handed its number to the next document. A
    number that identifies two documents in the same year is the one thing a
    register may not do, and it is why Odoo (``ir.sequence``) and ERPNext
    (Naming Series) both keep a stored counter rather than a maximum.

    One row per prefix, and the prefix already carries the type and the
    period, so a new year starts a new count on its own. ``next_value`` is the
    number the next document will be given.
    """

    __tablename__ = 'document_number_sequences'

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        primary_key=True,
    )
    #: The literal text every number under this counter starts with, after
    #: the placeholders are resolved — e.g. ``IN/2026/``.
    prefix: Mapped[str] = mapped_column(String(120), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
