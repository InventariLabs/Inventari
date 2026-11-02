import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from math import isfinite
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    cast,
    func,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym
from sqlalchemy.types import TypeDecorator

from app.core.file_reference import served_url, stored_reference
from app.core.open_package import OPENED_KEY, USE_BY_KEY, effective_expiry
from app.database import Base

if TYPE_CHECKING:
    from app.models.storage_location import StorageLocation


class FiniteNumeric(TypeDecorator):
    """Numeric column that refuses non-finite values and heals them on read.

    PostgreSQL's numeric happily stores ``Decimal('NaN')`` — and its own
    ``quantity >= 0`` CHECK passes it too, because NaN sorts above every
    number — but one such row made Pydantic refuse the whole items list
    (GET /items -> 400) and the audit/history JSONB serialization crash
    (DELETE -> 500). The Pydantic schemas (``ge=0``) only guard HTTP input;
    an ORM write like the bulk import's ``Item(**kwargs)`` bypasses them
    entirely.

    Writes: any non-finite value bound to the column raises ``ValueError``,
    on every path through SQLAlchemy — ORM attribute sets and Core
    ``update()`` statements alike.

    Reads: a value already sitting in the database (written before this
    guard existed) loads as ``nonfinite_read_default`` so the row stays
    readable and deletable from the app — one poisoned row must not take
    the whole result page down with it.
    """

    impl = Numeric
    cache_ok = True

    def __init__(
        self,
        precision: int,
        scale: int,
        *,
        nonfinite_read_default: Decimal | None,
    ) -> None:
        super().__init__(precision, scale)
        self.nonfinite_read_default = nonfinite_read_default

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError(f'expected a finite number, got {value!r}')
        if isinstance(value, float) and not isfinite(value):
            raise ValueError(f'expected a finite number, got {value!r}')
        return value

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if isinstance(value, Decimal) and not value.is_finite():
            return self.nonfinite_read_default
        return value


class Item(Base):
    """
    Inventory record stored in a specific location.
    """

    __tablename__ = 'items'
    __table_args__ = (
        Index('ix_items_org_not_deleted', 'organization_id', 'is_deleted'),
        Index(
            'ix_items_org_barcode_active', 'organization_id', 'barcode', 'is_deleted'
        ),
        # One active record per barcode in an organization — the rule the
        # migrations build, declared here so the test databases enforce it.
        Index(
            'uq_items_org_barcode_active',
            'organization_id',
            'barcode',
            unique=True,
            postgresql_where=text('barcode IS NOT NULL AND is_deleted = false'),
        ),
        Index(
            'ix_items_org_template_active',
            'organization_id',
            'template_id',
            'is_deleted',
        ),
        Index(
            'ix_items_org_category_active',
            'organization_id',
            'category_id',
            'is_deleted',
        ),
        Index(
            'ix_items_org_created',
            'organization_id',
            'is_deleted',
            text('created_at DESC'),
        ),
        Index('ix_items_meta_data_gin', 'meta_data', postgresql_using='gin'),
        Index(
            'uq_items_org_serial',
            'organization_id',
            'serial_number',
            unique=True,
            postgresql_where=text('serial_number IS NOT NULL AND is_deleted = false'),
        ),
        # The quant's key, read from the records' side: what one batch of one
        # owner holds on one shelf is a sum over this index. The quantity and
        # the deletion flag ride along, so the stock page's count and each
        # anchor's groups are read off the index alone (``stockpage01``).
        Index(
            'ix_items_stock_group',
            'organization_id',
            'template_id',
            'storage_location_id',
            'lot_id',
            'owner_id',
            postgresql_include=['quantity', 'is_deleted'],
        ),
        CheckConstraint('quantity >= 0', name='ck_items_quantity_nonneg'),
        # A record with a product stands in a group that has an anchor, the
        # row every write to the group locks (``core_api.stock.lock_async``
        # creates it). A door that writes a record into a new group without
        # that lock fails here instead of writing stock no lock covers.
        # MATCH SIMPLE: a record without a product is not checked.
        ForeignKeyConstraint(
            ['organization_id', 'template_id', 'storage_location_id'],
            [
                'stock_anchors.organization_id',
                'stock_anchors.product_template_id',
                'stock_anchors.storage_location_id',
            ],
            name='fk_items_stock_anchor',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    storage_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='CASCADE'),
        index=True,
    )
    #: The name the API and the contract DTOs give this column: a client
    #: meets a location, the table keeps its storage_location spelling.
    location_id: Mapped[uuid.UUID] = synonym('storage_location_id')
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('categories.id'))
    # Which vertical module this record belongs to, when one does. The general
    # lists use it to keep a module's data out of them; the category's own
    # ``context_tag`` still speaks first, so re-filing a record moves it. Set
    # from the ``meta_data`` namespace a module writes under (AGENTS.md
    # "meta_data namespace convention"), never from the request body.
    module_name: Mapped[str | None] = mapped_column(String(50), index=True)

    name: Mapped[str] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(500))
    uom_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('uoms.id')
    )  # New UoM system
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('product_templates.id')
    )  # Logistics 2.0
    # The `quantity >= 0` CHECK in __table_args__ does NOT stop NaN:
    # PostgreSQL sorts NaN above every number, so the comparison is true.
    # FiniteNumeric is the real gate.
    # The same width the quant table kept and the records' view sums into: a
    # record narrower than the sums it feeds cannot hold every value they
    # can. The column was widened by migration and the model was left
    # saying the old number, so every schema built from the model — the test
    # databases among them — was narrower than production, and the next
    # autogenerated migration would have offered to narrow production too.
    quantity: Mapped[Decimal] = mapped_column(
        FiniteNumeric(12, 3, nonfinite_read_default=Decimal('1.0')),
        default=1.0,
        index=True,
    )
    # A code for a record that has no template. The barcode of a *product*
    # belongs to ``product_templates.barcode`` — that is where a receipt
    # writes it and where a scan reads it — and this column stays for the one
    # case there is no catalogue row to ask: a one-off nobody catalogued.
    # ``uq_items_org_barcode_active`` allows a single active bearer, which is
    # why it cannot answer "how much of this product do I have" for stock
    # standing in two places.
    barcode: Mapped[str | None] = mapped_column(String(50), index=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), index=True)

    added_date: Mapped[date] = mapped_column(Date, default=date.today)
    # expiry_date: justified 3-vertical exception (food/pharma/cosmetics, indexed
    # for FEFO rotation). See backend/AGENTS.md §4, "Permitted exceptions on Item".
    # freeze_date was moved to meta_data['food']['freeze_date']; the API
    # field is preserved via a meta_data-backed shim (services/items/_date_meta.py).
    # production_date was moved to meta_data['manufacturing']['production_date']
    # — dead column, no API consumers existed.
    expiry_date: Mapped[date | None] = mapped_column(Date, index=True)

    shelf_location: Mapped[str | None] = mapped_column(
        String(255)
    )  # e.g. "Top Drawer", "Shelf 2"
    #: The cover picture's reference, never its address: the org-scoped storage
    #: key the upload wrote (``<org>/items/<item_id>/cover.<ext>``) or a foreign
    #: ``http(s)`` address for a picture that lives on somebody else's server.
    #: ``image_url`` below builds the address a reader is given, so moving the
    #: files or switching storage backends changes no row. The column keeps its
    #: historical name; see ``app.core.file_reference`` and
    #: ``docs/subsystems/FILE_STORAGE.md``.
    image_key: Mapped[str | None] = mapped_column('image_url', String(500))
    meta_data: Mapped[dict[str, Any] | None] = mapped_column(
        postgresql.JSONB
    )  # Vision LLM info, user notes

    # COST TRACKING
    purchase_price: Mapped[Decimal | None] = mapped_column(
        # An empty spreadsheet cell in this column reads as float('nan') the
        # same way it does for quantity — the same poisoned row, the same
        # page-killing read. Heals to NULL on read: the natural
        # "unknown" for an optional price.
        FiniteNumeric(10, 2, nonfinite_read_default=None)
    )  # purchase price
    currency: Mapped[str | None] = mapped_column(String(3))
    # `price_per_unit` used to sit here, commented "price per kg/L". Nothing
    # ever wrote it and nothing read it — `GET /items` returned null for every
    # row since the initial schema. Meanwhile `purchase_price` above *is* the
    # per-unit rate: it opens a valuation layer at that unit cost, AVCO comes
    # off those layers, and a production cost is rate × quantity. Two columns
    # with one meaning and the opposite names is how a form comes to suggest
    # the wrong one, so the one that was never filled in is gone.

    # SOFT DELETE
    is_deleted: Mapped[bool] = mapped_column(default=False, index=True)
    is_catalog_entry: Mapped[bool] = mapped_column(default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id'))
    deletion_reason: Mapped[str | None] = mapped_column(
        String(100)
    )  # USED, DISPOSED, DAMAGED, LOST, EXPIRED

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    organization: Mapped['Organization'] = relationship(back_populates='items')  # type: ignore[name-defined]
    storage_location: Mapped['StorageLocation'] = relationship(
        back_populates='items', lazy='selectin'
    )  # type: ignore[name-defined]
    category: Mapped['Category | None'] = relationship(  # type: ignore[name-defined]
        back_populates='items', lazy='selectin'
    )
    uom: Mapped['Uom | None'] = relationship(lazy='selectin')  # type: ignore[name-defined]
    template: Mapped['ProductTemplate | None'] = relationship(  # type: ignore[name-defined]
        back_populates='items', lazy='selectin'
    )
    history: Mapped[list['ItemHistory']] = relationship(  # type: ignore[name-defined]
        back_populates='item', cascade='all, delete-orphan'
    )
    stock_take_items: Mapped[list['StockTakeItem']] = relationship(  # type: ignore[name-defined]
        back_populates='item'
    )
    attachments: Mapped[list['ItemAttachment']] = relationship(  # type: ignore[name-defined]
        back_populates='item', cascade='all, delete-orphan'
    )
    # label_code references label_pool.short_code but has NO database FK: the
    # referenced column is only unique per-organization, so a single-column FK
    # cannot be expressed. Integrality is enforced in the app layer (the label
    # API is the sole writer of this column).
    label_code: Mapped[str | None] = mapped_column(String(20))

    # Partner / supplier link (core entity)
    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('partners.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    partner: Mapped['Partner | None'] = relationship(  # type: ignore[name-defined]
        'Partner',
        back_populates='items',
        lazy='select',
        foreign_keys=[partner_id],
    )

    # The batch and the owner this record's stock belongs to — the two
    # members of a quant's key the record did not carry. The stock model
    # keeps one record per batch per owner, so the records' quantities are
    # the only stock number and a quant is their sum.
    # Existing records were assigned by migration (``lotrec02``). A record's
    # posting and its move change the record's own batch and owner, and so do
    # production, stock takes and the document executor (backend/AGENTS.md
    # §4).
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('stock_lots.id', ondelete='SET NULL'),
        nullable=True,
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('partners.id', ondelete='SET NULL'),
        nullable=True,
    )

    # A handle for a path that does not exist yet. Nothing writes this
    # column: no caller's ``source_document_id`` reaches it — document
    # executors do pass the parameter into ``create_item_async``, which
    # spends it on the ItemHistory row alone
    # (``services/items/_create.py``) — the UI offers no way to set it, and
    # production holds zero populated rows, measured org-wide. Provenance is answered today by
    # ``ItemHistory.source_document_id``, one row per event, and a
    # COMPLETED document can be neither cancelled nor deleted, so the
    # ``SET NULL`` here fires only under raw SQL. Populating it is a
    # decision to make when a creation-from-document path is actually
    # built — which document of a line's life is "the" source, and whether
    # one column may speak for events ItemHistory already records — and
    # the first populated row silently arms the ``source_document_id``
    # filter on the items list endpoints.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('documents.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    source_document: Mapped['Document | None'] = relationship(  # type: ignore[name-defined]
        'Document',
        lazy='select',
    )

    def __repr__(self):
        return f'<Item(name="{self.name}", brand="{self.brand}", quantity={self.quantity})>'

    @hybrid_property
    def effective_expiry_date(self) -> date | None:
        """The earlier of the batch's date and the use-by given at opening."""
        return effective_expiry(self.expiry_date, self.meta_data)

    @effective_expiry_date.inplace.expression
    @classmethod
    def _effective_expiry_date_expression(cls):
        """The same rule in SQL; ``least`` skips the side that has no date."""
        use_by = cast(cls.meta_data[OPENED_KEY][USE_BY_KEY].astext, Date)
        return func.least(cls.expiry_date, use_by)

    @hybrid_property
    def image_url(self) -> str | None:
        """The cover address a reader loads, built from :attr:`image_key`.

        Computed, never stored: the row names the object, the configured
        backend answers it. A foreign address kept on the row is returned as
        it is.
        """
        return served_url(self.image_key)

    @image_url.inplace.setter
    def _image_url_setter(self, value: str | None) -> None:
        self.image_key = stored_reference(value)

    @image_url.inplace.expression
    @classmethod
    def _image_url_expression(cls):
        """Filters on the column: ``Item.image_url.is_(None)`` keeps working."""
        return cls.image_key

    @property
    def min_quantity(self) -> float | None:
        if self.template is not None and self.template.min_quantity:
            return float(self.template.min_quantity)
        return None

    @property
    def total_weight(self) -> Decimal | None:
        """Weight of this line, in kilograms (or litres for volume).

        Two cases. An item counted in a weight or volume unit carries its
        weight in the quantity itself — 500 g is the weight. Anything counted
        in pieces takes the unit weight from its product template and
        multiplies.

        Computed, never stored — see ``app.services.items.weight`` and
        ADR-015 for why the unit weight belongs to the product.
        """
        from app.services.items.weight import (
            CONTINUOUS_UOM_CATEGORIES,
            quantity_as_weight,
            total_weight,
        )

        if (
            self.uom is not None
            and self.uom.category is not None
            and self.uom.category.name in CONTINUOUS_UOM_CATEGORIES
        ):
            return quantity_as_weight(self.quantity, self.uom.factor)

        if self.template is None:
            return None
        return total_weight(
            self.quantity,
            self.template.weight_value,
            self.template.weight_uom.factor if self.template.weight_uom else None,
        )

    @property
    def total_weight_unit(self) -> str | None:
        """Which unit ``total_weight`` is expressed in: ``kg`` or ``l``.

        The number alone cannot say. A reader — or a report — that assumes
        kilograms labels every drink wrongly, so the unit travels with the
        value instead of being guessed at the far end.

        Whichever unit produced the number names it. A line counted in a
        continuous unit carries its own; a line counted in pieces took the
        weight from its template, so the template's unit comes with it — six
        1.5 l bottles are nine litres, not nine kilograms. Only a product
        nobody assigned a weight unit to falls back to kilograms, which is
        the same assumption ``total_weight`` makes when there is no factor.
        """
        from app.services.items.weight import (
            CONTINUOUS_UOM_CATEGORIES,
            VOLUME_UOM_CATEGORY,
        )

        if self.total_weight is None:
            return None

        own_category = (
            self.uom.category.name
            if self.uom is not None and self.uom.category is not None
            else None
        )
        if own_category in CONTINUOUS_UOM_CATEGORIES:
            return 'l' if own_category == VOLUME_UOM_CATEGORY else 'kg'

        weight_uom = self.template.weight_uom if self.template is not None else None
        if (
            weight_uom is not None
            and weight_uom.category is not None
            and weight_uom.category.name == VOLUME_UOM_CATEGORY
        ):
            return 'l'
        return 'kg'

    @property
    def storage_location_name(self) -> str | None:
        return self.storage_location.name if self.storage_location else None

    @property
    def location_name(self) -> str | None:
        """The name the API gives :attr:`storage_location_name`."""
        return self.storage_location_name

    @property
    def uom_symbol(self) -> str | None:
        return self.uom.symbol if self.uom else None

    @property
    def template_name(self) -> str | None:
        return self.template.name if self.template else None
