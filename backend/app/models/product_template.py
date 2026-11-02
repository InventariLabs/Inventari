import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.file_reference import served_url, stored_reference
from app.database import Base


class ProductTemplate(Base):
    """
    Defines the product/item catalog entry (SKU).
    Items are instances of a ProductTemplate stored in a specific location.
    """

    __tablename__ = 'product_templates'
    __table_args__ = (
        # A barcode and a SKU each name one catalogue entry per organization;
        # an absent one names nothing and may repeat.
        Index(
            'uq_templates_org_barcode',
            'organization_id',
            'barcode',
            unique=True,
            postgresql_where=text('barcode IS NOT NULL'),
        ),
        Index(
            'uq_templates_org_sku',
            'organization_id',
            'sku',
            unique=True,
            postgresql_where=text('sku IS NOT NULL'),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # Global templates (system) or Organization specific
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(255))
    barcode: Mapped[str | None] = mapped_column(String(50), index=True)  # EAN/GTIN
    sku: Mapped[str | None] = mapped_column(String(50), index=True)

    uom_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('uoms.id'))

    # Conversion helpers (Logistics 2.0)
    # Allows linking discrete units (Pieces) to physical measures (Weight/Volume)
    # e.g. 1 Piece = 500g
    # Exact, like the unit factors they are multiplied by: ``numeric * double``
    # is ``double`` in SQL, so one approximate column here would have pulled
    # every weight total computed in the database into floating point.
    weight_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    weight_uom_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('uoms.id'))

    volume_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    volume_uom_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('uoms.id'))

    #: The catalogue picture's reference, never its address: the org-scoped
    #: storage key the upload wrote or a foreign ``http(s)`` address for a
    #: picture kept from somebody else's catalogue. ``image_url`` below builds
    #: the address a reader is given; the column keeps its historical name.
    image_key: Mapped[str | None] = mapped_column('image_url', String(500))
    description: Mapped[str | None] = mapped_column(String(500))

    # Stock Management (Thresholds)
    min_quantity: Mapped[float | None] = mapped_column(
        postgresql.DOUBLE_PRECISION, default=0.0
    )

    # AVCO valuation used to be cached here, in `current_valuation_rate`. It
    # cannot live on this row: valuation layers belong to an organization, and
    # a global template — the whole default catalogue — is one row shared by
    # every organization, so the cached number belonged to whichever one had
    # last taken a delivery. One organization read another's purchase cost off
    # a catalogue product, and valued its own stock with it.
    #
    # The rate is computed per organization from its own layers instead;
    # `core_api.valuation.get_current_rate_async` and its batch counterpart are
    # the readers. There is no cache to keep in step with anything.

    # Removal strategy: FIFO (default) or FEFO.
    # Resolved at decrement time via app.services.stock_service.resolve_removal_strategy.
    # Set per product: FEFO where the earliest expiry has to leave first,
    # FIFO where age alone decides.
    removal_strategy: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Module-owned enrichment payloads (nutrition, specs, etc.)
    # Each module writes under its own namespace key, e.g. meta_data['nutrition'].
    meta_data: Mapped[dict[str, Any] | None] = mapped_column(postgresql.JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    organization: Mapped['Organization'] = relationship()  # type: ignore[name-defined]
    uom: Mapped['Uom | None'] = relationship(foreign_keys=[uom_id], lazy='selectin')  # type: ignore[name-defined]
    # Eager: Item.total_weight reads this factor while the response is being
    # serialised, where a lazy load would run outside the async greenlet.
    weight_uom: Mapped['Uom | None'] = relationship(  # type: ignore[name-defined]
        foreign_keys=[weight_uom_id], lazy='selectin'
    )
    volume_uom: Mapped['Uom | None'] = relationship(foreign_keys=[volume_uom_id])  # type: ignore[name-defined]
    items: Mapped[list['Item']] = relationship(back_populates='template')  # type: ignore[name-defined]

    def __repr__(self):
        return f'<ProductTemplate(name="{self.name}", barcode="{self.barcode}")>'

    @hybrid_property
    def image_url(self) -> str | None:
        """The picture address a reader loads, built from :attr:`image_key`."""
        return served_url(self.image_key)

    @image_url.inplace.setter
    def _image_url_setter(self, value: str | None) -> None:
        self.image_key = stored_reference(value)

    @image_url.inplace.expression
    @classmethod
    def _image_url_expression(cls):
        """Filters on the column, not on the computed address."""
        return cls.image_key
