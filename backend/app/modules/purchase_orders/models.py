"""Purchase Order database models."""

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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.database import Base


class PurchaseOrder(Base):
    """Purchase Order header."""

    __tablename__ = 'purchase_orders'
    __table_args__ = (
        UniqueConstraint(
            'organization_id', 'number', name='uq_purchase_orders_org_number'
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )

    number: Mapped[str] = mapped_column(String(50), index=True)

    status: Mapped[str] = mapped_column(String(20), default='DRAFT', index=True)

    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('partners.id', ondelete='SET NULL'),
    )

    scheduled_date: Mapped[date | None] = mapped_column(Date)

    notes: Mapped[str | None] = mapped_column(Text)

    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)

    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))

    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id'))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id'))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    lines: Mapped[list['PurchaseOrderLine']] = relationship(
        back_populates='purchase_order',
        cascade='all, delete-orphan',
        order_by='PurchaseOrderLine.line_number',
        lazy='selectin',
    )

    organization: Mapped['Organization'] = relationship(lazy='selectin')  # type: ignore[name-defined]
    partner: Mapped['Partner | None'] = relationship(lazy='selectin')  # type: ignore[name-defined]

    def __repr__(self) -> str:
        return f'<PurchaseOrder(number="{self.number}", status="{self.status}")>'


class PurchaseOrderLine(Base):
    """Purchase Order line item."""

    __tablename__ = 'purchase_order_lines'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('purchase_orders.id', ondelete='CASCADE'),
        index=True,
    )

    product_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('product_templates.id', ondelete='SET NULL'),
    )

    name: Mapped[str] = mapped_column(String(255))

    quantity_ordered: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    quantity_received: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), default=Decimal('0')
    )

    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    uom_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('uoms.id'), nullable=True
    )

    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    line_number: Mapped[int] = mapped_column(default=1)

    notes: Mapped[str | None] = mapped_column(Text)

    # Provenance for alert-driven drafts: the reorder rule whose alert
    # created this line. One draft PO groups several rules under a
    # supplier, so the reference lives on the line, not the header.
    source_reorder_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('po_reorder_rules.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    purchase_order: Mapped['PurchaseOrder'] = relationship(
        back_populates='lines', lazy='selectin'
    )
    product_template: Mapped['ProductTemplate | None'] = relationship(lazy='selectin')  # type: ignore[name-defined]
    uom: Mapped['Uom | None'] = relationship(lazy='joined', foreign_keys=[uom_id])  # type: ignore[name-defined]

    def __repr__(self) -> str:
        return f'<PurchaseOrderLine(name="{self.name}", qty={self.quantity_ordered})>'


class ReorderRule(Base):
    """Per-location reorder thresholds.

    Each row says: "for product P at location L, trigger a reorder when
    available stock drops below ``min_quantity``, target ``max_quantity``
    on replenishment, and never go below ``safety_stock`` (used by the
    PO generator as a hard floor).

    Lives in the ``purchase_orders`` module because:
      - Replenishment is a procurement decision (when/what to buy).
      - Draft-PO generation from alerts reads these rules directly
        (``replenishment_service.create_draft_pos_from_alerts_async``).
      - Per-location granularity is the main value-add over the flat
        ``ProductTemplate.min_quantity`` field, which is org-global.

    Kept module-local (no Core model leak) per the module-ownership
    rules in AGENTS.md.
    """

    __tablename__ = 'po_reorder_rules'
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'product_template_id',
            'storage_location_id',
            name='uq_po_reorder_rules_org_product_loc',
        ),
        CheckConstraint(
            'min_quantity >= 0',
            name='ck_po_reorder_rules_min_nonneg',
        ),
        CheckConstraint(
            'max_quantity >= min_quantity',
            name='ck_po_reorder_rules_max_ge_min',
        ),
        CheckConstraint(
            'safety_stock >= 0',
            name='ck_po_reorder_rules_safety_nonneg',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )

    product_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        index=True,
    )

    storage_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='CASCADE'),
        index=True,
    )
    #: The name the API and the contract DTOs give this column: a client
    #: meets a location, the table keeps its storage_location spelling.
    location_id: Mapped[uuid.UUID] = synonym('storage_location_id')

    min_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal('0'))
    max_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    safety_stock: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal('0'))

    preferred_partner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('partners.id', ondelete='SET NULL'),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    product_template: Mapped['ProductTemplate'] = relationship(lazy='selectin')  # type: ignore[name-defined]
    storage_location: Mapped['StorageLocation'] = relationship(lazy='selectin')  # type: ignore[name-defined]
    preferred_partner: Mapped['Partner | None'] = relationship(lazy='selectin')  # type: ignore[name-defined]

    @property
    def product_name(self) -> str:
        """Display name for API responses (relationship is selectin-loaded)."""
        return self.product_template.name if self.product_template else ''

    @property
    def preferred_partner_name(self) -> str | None:
        """The preferred supplier's name, ``None`` when the rule names none.

        The relationship is selectin-loaded, so the list of rules carries the
        names without a read per supplier.
        """
        return self.preferred_partner.name if self.preferred_partner else None

    @property
    def uom_id(self) -> uuid.UUID | None:
        """Unit of the product this rule replenishes.

               Edit mode needs it so the threshold fields show the product's unit
        instead of dropping it. The template relationship is
               selectin-loaded; its ``uom_id`` is a plain column, so this never
               triggers an extra query.
        """
        return self.product_template.uom_id if self.product_template else None

    @property
    def uom_symbol(self) -> str | None:
        """Symbol of the product's unit, or ``None`` when it has none."""
        template = self.product_template
        if template is None or template.uom is None:
            return None
        symbol: str = template.uom.symbol
        return symbol

    def __repr__(self) -> str:
        return (
            f'<ReorderRule(product={self.product_template_id}, '
            f'loc={self.storage_location_id}, min={self.min_quantity})>'
        )


class PartnerPricelist(Base):
    """Per-supplier price list entry.

    Each row says: "supplier P charges ``unit_price`` per ``uom_id`` for
    product T, with tier ``min_quantity`` threshold, valid between
    ``valid_from`` and ``valid_to``."

    Lives in the ``purchase_orders`` module because:
      - Supplier pricing is a procurement concept (alongside ReorderRule).
      - The recipes cost estimate reads supplier price as the
        fallback before the static ``Item.purchase_price``.
      - Procurement UI compares offers for the same product across
        suppliers.

    Module-local table — no Core model leak. Reads exposed via
    ``core_api.purchase_orders.list_pricelist_*_async``.
    """

    __tablename__ = 'po_partner_pricelist'
    __table_args__ = (
        CheckConstraint(
            'unit_price > 0',
            name='ck_po_partner_pricelist_unit_price_positive',
        ),
        CheckConstraint(
            'valid_to IS NULL OR valid_to >= valid_from',
            name='ck_po_partner_pricelist_valid_range',
        ),
        CheckConstraint(
            'min_quantity IS NULL OR min_quantity > 0',
            name='ck_po_partner_pricelist_min_qty_positive',
        ),
        # The "best price for a template at a date" lookup.
        Index(
            'ix_po_partner_pricelist_template_active',
            'product_template_id',
            'valid_from',
            'valid_to',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )

    partner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('partners.id', ondelete='CASCADE'),
        index=True,
    )

    product_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        index=True,
    )

    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    currency: Mapped[str] = mapped_column(String(3), default='USD')

    uom_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('uoms.id', ondelete='SET NULL'), nullable=True
    )

    min_quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)

    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    partner: Mapped['Partner'] = relationship(lazy='selectin')  # type: ignore[name-defined]
    product_template: Mapped['ProductTemplate'] = relationship(lazy='selectin')  # type: ignore[name-defined]
    uom: Mapped['Uom | None'] = relationship(lazy='joined', foreign_keys=[uom_id])  # type: ignore[name-defined]

    @property
    def product_name(self) -> str:
        """Display name for API responses (relationship is selectin-loaded)."""
        return self.product_template.name if self.product_template else ''

    def __repr__(self) -> str:
        return (
            f'<PartnerPricelist(partner={self.partner_id}, '
            f'template={self.product_template_id}, price={self.unit_price} {self.currency})>'
        )


class POSettings(Base):
    """Per-org purchase order settings (approval config).

    ``approval_threshold``: POs with net total above this amount require
    approval before they can be confirmed (``None`` = no threshold).
    ``approval_required``: when true, every PO confirmation parks the
    PO in PENDING_APPROVAL (threshold ignored).
    """

    __tablename__ = 'po_settings'
    __table_args__ = (UniqueConstraint('organization_id', name='uq_po_settings_org'),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    approval_threshold: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    approval_required: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return (
            f'<POSettings(org={self.organization_id}, '
            f'approval_required={self.approval_required}, '
            f'approval_threshold={self.approval_threshold})>'
        )
