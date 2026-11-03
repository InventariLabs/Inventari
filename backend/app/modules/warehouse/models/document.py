"""Document and DocumentLine models with their enums."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.module_sdk import CoreModelBase
from app.core.utils import safe_get_loaded_attr


class DocumentType(StrEnum):
    """Country-neutral by design — see ``document_types`` for the legacy map."""

    IN = 'IN'
    OUT = 'OUT'
    INT = 'INT'
    INTERNAL_IN = 'INTERNAL_IN'
    INTERNAL_OUT = 'INTERNAL_OUT'
    CORRECTION = 'CORRECTION'
    ADJUSTMENT = 'ADJUSTMENT'
    SCRAP = 'SCRAP'


class DocumentStatus(StrEnum):
    DRAFT = 'DRAFT'
    PENDING_APPROVAL = 'PENDING_APPROVAL'
    CONFIRMED = 'CONFIRMED'
    COMPLETED = 'COMPLETED'
    CANCELLED = 'CANCELLED'


class DocumentDiscrepancyCode(StrEnum):
    SHORTAGE = 'SHORTAGE'
    DAMAGE = 'DAMAGE'
    QUALITY_HOLD = 'QUALITY_HOLD'
    COUNT_VARIANCE = 'COUNT_VARIANCE'
    #: More arrived than the paperwork said — the code an over-receipt
    #: line must carry, the way a short line carries SHORTAGE.
    SURPLUS = 'SURPLUS'
    OTHER = 'OTHER'


#: Codes under which a receipt line's quantity is held back instead of
#: becoming stock a picking can draw: damaged goods and goods waiting for a
#: quality decision are in the building but not for sale.
QUARANTINE_CODES = frozenset(
    {DocumentDiscrepancyCode.DAMAGE.value, DocumentDiscrepancyCode.QUALITY_HOLD.value}
)

#: Codes that explain a line left short of its quantity in a way that still
#: owes the order the rest: the missing part is asked for again on a
#: backorder.
BACKORDER_CODES = frozenset({DocumentDiscrepancyCode.SHORTAGE.value}) | QUARANTINE_CODES


class CorrectionReasonCode(StrEnum):
    """Why a correction is raised.

    Free text answers "what happened here"; it cannot answer "how often does
    this happen". A correction therefore carries a code from this list *and*
    a note. OTHER is the escape hatch, and the note stops being optional
    whenever it is chosen — otherwise the escape hatch is the answer nobody
    can read.
    """

    WRONG_QUANTITY = 'WRONG_QUANTITY'
    WRONG_PRODUCT = 'WRONG_PRODUCT'
    WRONG_PRICE = 'WRONG_PRICE'
    DATA_ENTRY_ERROR = 'DATA_ENTRY_ERROR'
    OTHER = 'OTHER'


class ReturnReasonCode(StrEnum):
    """Why goods come back — same bargain as CorrectionReasonCode."""

    DAMAGED = 'DAMAGED'
    WRONG_ITEM = 'WRONG_ITEM'
    QUALITY = 'QUALITY'
    NOT_NEEDED = 'NOT_NEEDED'
    OTHER = 'OTHER'


class ScrapReasonCode(StrEnum):
    """Why goods are written off — same bargain as CorrectionReasonCode.

    A scrap that names no reason cannot answer "what did damaged goods cost
    us" next to "what did expired goods cost us"; the code is what a report
    groups by, the note says the rest.
    """

    DAMAGED = 'DAMAGED'
    EXPIRED = 'EXPIRED'
    QUALITY = 'QUALITY'
    OTHER = 'OTHER'


FREE_TEXT_REASON_CODE = 'OTHER'


class DocumentLineStatus(StrEnum):
    PENDING = 'PENDING'
    DONE = 'DONE'
    PARTIAL = 'PARTIAL'
    EXCEPTION = 'EXCEPTION'


class Document(CoreModelBase):
    """Warehouse document — tracks stock operations with full audit trail."""

    __tablename__ = 'documents'
    __table_args__ = (
        UniqueConstraint('organization_id', 'number', name='uq_document_org_number'),
        Index('ix_document_org_type_status', 'organization_id', 'type', 'status'),
        Index('ix_document_org_partner', 'organization_id', 'partner_id'),
        # One document per press: see ``post_key``.
        Index(
            'uq_document_org_post_key',
            'organization_id',
            'post_key',
            unique=True,
            postgresql_where=text('post_key IS NOT NULL'),
        ),
        # The register filters and sorts by the window over one status
        #: without this index every page sorted the whole
        # matching set, so pagination moved the cost instead of removing it.
        Index(
            'ix_document_org_status_created_at',
            'organization_id',
            'status',
            'created_at',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(15), nullable=False)
    #: The register's number once the document is confirmed; until then
    #: the draft's own temporary identifier, drawn from no series (see
    #: ``document_numbering_service.temporary_number``).
    number: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DocumentStatus.DRAFT.value
    )

    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('partners.id', ondelete='SET NULL'), nullable=True
    )
    source_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'), nullable=True
    )
    target_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'), nullable=True
    )
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # A receipt that opens the books rather than records a purchase: the
    # stock a company brought in from its spreadsheet the day it started.
    # Reports and the partner requirement tell the two apart by this, not by
    # a note somebody may or may not have written.
    is_opening: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text('false')
    )

    # A record of a movement somebody else already applied to the shelves: the
    # picking session takes each ingredient off as it is picked, and the RW it
    # registers afterwards is the register's copy. Confirming such a document
    # holds nothing and completing it moves nothing, because the stock is
    # already gone. Set by the module that applied the movement, never by the
    # document schemas: a flag a client could send would be a way to complete
    # an issue without issuing it.
    stock_already_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text('false')
    )

    #: The document was submitted through the one-step action, which promised
    #: to post it as well as confirm it. The approval stands between the two,
    #: so the promise is remembered here and kept when the request is granted
    #: (see ``confirm_after_approval``). Documents confirmed through the
    #: planned path leave it false: their approval ends at the confirmation.
    complete_on_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text('false')
    )

    #: The module a document in PENDING_APPROVAL waits for: the one whose
    #: pre-post check held it at confirmation, or that asked for the hold
    #: afterwards (see ``pre_post_checks``). Only that module releases it, and
    #: its hold stands down while the module is switched off for the
    #: organization. Empty on every document nothing holds.
    held_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: The key the screen sent with the press that created and posted this
    #: document. A repeat of the same press (a double click, a retry after the
    #: answer was lost) finds the document by it and is answered with it
    #: instead of making a second (see ``post_new_document``). Absent on
    #: documents made any other way.
    post_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    partner_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )

    #: The rest of what the printout states about the parties, frozen at
    #: confirmation like the partner: ``issuer`` (the organization's name, tax
    #: id and address, see ``core.print_identity.issuer_snapshot``) and the
    #: ``source_location`` / ``target_location`` names. The logo and the
    #: layout stay live. Empty on documents confirmed before it existed, which
    #: print from live data.
    print_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    #: Other modules' own fields on this document, each under the module's
    #: name (``{'<module>': {...}}``): a field one customer needs is not a
    #: column here. Read by the pre-post checks; copied onto a correction or
    #: a return. Never a flat key — see AGENTS.md §4, "meta_data namespace
    #: convention".
    meta_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Why this document exists, as one of a closed list — set on corrections,
    # returns and scrap. `notes` says the rest; this is the part that can be
    # counted, filtered and reported on.
    reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)

    corrects_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('documents.id', ondelete='RESTRICT'),
        nullable=True,
        index=True,
    )
    corrected_document: Mapped[Document | None] = relationship(
        'Document',
        foreign_keys='Document.corrects_document_id',
        remote_side='Document.id',
        lazy='select',
    )

    backorder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('documents.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    backorder_of: Mapped[Document | None] = relationship(
        'Document',
        foreign_keys='Document.backorder_id',
        remote_side='Document.id',
        lazy='select',
    )

    total_net: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_gross: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)

    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=False
    )
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    creator = relationship('User', foreign_keys=[created_by], lazy='selectin')
    confirmer = relationship('User', foreign_keys=[confirmed_by], lazy='selectin')
    completer = relationship('User', foreign_keys=[completed_by], lazy='selectin')
    canceller = relationship('User', foreign_keys=[cancelled_by], lazy='selectin')

    lines: Mapped[list[DocumentLine]] = relationship(
        'DocumentLine',
        back_populates='document',
        cascade='all, delete-orphan',
        lazy='selectin',
        order_by='DocumentLine.line_number',
    )
    partner = relationship('Partner', lazy='selectin')
    source_location = relationship(
        'StorageLocation', foreign_keys=[source_location_id], lazy='selectin'
    )
    target_location = relationship(
        'StorageLocation', foreign_keys=[target_location_id], lazy='selectin'
    )

    @property
    def confirmed_by_name(self) -> str | None:
        if self.confirmer:
            return cast(str | None, self.confirmer.full_name or self.confirmer.email)
        return None

    @property
    def created_by_name(self) -> str | None:
        if self.creator:
            return cast(str | None, self.creator.full_name or self.creator.email)
        return None

    @property
    def completed_by_name(self) -> str | None:
        if self.completer:
            return cast(str | None, self.completer.full_name or self.completer.email)
        return None

    @property
    def cancelled_by_name(self) -> str | None:
        if self.canceller:
            return cast(str | None, self.canceller.full_name or self.canceller.email)
        return None


class DocumentLine(CoreModelBase):
    """Single line item within a warehouse document."""

    __tablename__ = 'document_lines'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('documents.id', ondelete='CASCADE'), index=True, nullable=False
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('items.id', ondelete='SET NULL'), nullable=True
    )
    product_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('product_templates.id', ondelete='SET NULL'), nullable=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(50), nullable=True)

    @property
    def sku(self) -> str | None:
        if self.product_snapshot and isinstance(self.product_snapshot, dict):
            val = self.product_snapshot.get('sku')
            if val:
                return cast(str, val)
        sku = safe_get_loaded_attr(self, 'product_template', 'sku')
        if sku:
            return cast(str, sku)
        item = safe_get_loaded_attr(self, 'item')
        if item is not None:
            template = safe_get_loaded_attr(item, 'template')
            if template is not None:
                return cast(str | None, safe_get_loaded_attr(template, 'sku'))
        return None

    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    expected_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    done_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    #: How much of ``done_quantity`` is received but held back — damaged or
    #: awaiting a quality decision. It is booked, but not as stock a picking
    #: can draw, and it does not fulfil the order the line belongs to. Zero
    #: says the delivery is ordinary stock, which is every line that never
    #: mentions it.
    held_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, server_default=text('0'), default=Decimal('0')
    )
    #: ``expected_quantity`` is a count somebody typed to get a row on the
    #: receive sheet, not a promise from an order or a delivery note. Such a
    #: line has no expectation to exceed, so receiving more is not a surplus.
    expected_is_count: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text('false'), default=False
    )
    uom_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('uoms.id'), nullable=True
    )
    batch_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    discrepancy_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    discrepancy_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    line_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    line_tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    line_gross: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_po_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    #: The line of an earlier document this one restates — set on the lines of
    #: a correction and of a return.
    #:
    #: Two questions need it. How much of that line has already been taken
    #: back, so a chain of corrections is checked against what is left rather
    #: than against the original every time. And which receipt the goods
    #: arrived on, so taking them back off the shelf takes them off the layer
    #: they were priced on instead of whichever happens to be oldest.
    corrects_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('document_lines.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    #: The receipt line whose goods this line carries out of a receiving
    #: area — set on the line of a putaway move. What a receipt line still
    #: has waiting there is what it received less what these lines took.
    puts_away_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('document_lines.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    # Where the goods of this line actually went, which is not always where
    # the document asked: a putaway rule can send a delivery to another
    # shelf, and the document used to say nothing about it.
    executed_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'), nullable=True
    )
    # The shelf this line takes from when the document's source is a zone:
    # pinned at confirmation, cleared when the hold is let go, so a line the
    # document does not pin still reads the document's own source.
    source_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'), nullable=True
    )
    # The shelf the worker named on this line, ahead of execution. Unset
    # lines keep following the putaway rule and the document; a set one
    # outranks the rule — a rule speaks about goods, not about the shelf a
    # person is standing at — and the serial-number record still outranks
    # the line, one physical thing staying whole.
    target_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'), nullable=True
    )
    # ``planned_*`` transient attributes are set at read time by
    # ``_receipt_planning.attach_receipt_plans`` and read by the line schema:
    # where the line's goods WILL land while the document still waits for
    # execution, and who decided it. Deliberately not declared as class
    # attributes — a stored plan would go stale the moment a rule changed,
    # the same way a booked "landed elsewhere" used to surprise.
    product_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    #: Other modules' own fields on this line, under each module's name, as
    #: on the document.
    meta_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    document: Mapped[Document] = relationship('Document', back_populates='lines')
    item = relationship('Item', lazy='selectin')
    product_template = relationship('ProductTemplate', lazy='selectin')
    uom = relationship('Uom', lazy='selectin', foreign_keys=[uom_id])
    executed_location = relationship(
        'StorageLocation', lazy='selectin', foreign_keys=[executed_location_id]
    )
    source_location = relationship(
        'StorageLocation', lazy='selectin', foreign_keys=[source_location_id]
    )

    @property
    def executed_location_name(self) -> str | None:
        """Where the goods went, for a reader who does not hold UUIDs."""
        return cast(str | None, safe_get_loaded_attr(self, 'executed_location', 'name'))

    @property
    def source_location_name(self) -> str | None:
        """The shelf a zone's line takes from, for a reader who does not hold UUIDs."""
        return cast(str | None, safe_get_loaded_attr(self, 'source_location', 'name'))

    @property
    def line_status(self) -> str:
        if self.discrepancy_code:
            return DocumentLineStatus.EXCEPTION.value
        if self.done_quantity >= self.expected_quantity:
            return DocumentLineStatus.DONE.value
        if self.done_quantity > 0:
            return DocumentLineStatus.PARTIAL.value
        return DocumentLineStatus.PENDING.value
