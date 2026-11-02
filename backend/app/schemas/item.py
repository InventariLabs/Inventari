from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

from app.core.exceptions import ServiceRejectionError
from app.core.open_package import effective_expiry, use_by_of
from app.schemas.category import Category
from app.schemas.pagination import PaginatedResponse
from app.schemas.product_template import ProductTemplate
from app.schemas.uom import UomInfoWithCategory
from app.schemas.validators import (
    QUANTITY_MAX,
    RemovalStrategy,
    decimal_from_int_float,
    empty_string_to_none,
    normalize_barcode,
    normalize_sku,
    quantize_quantity,
)

#: Item responses carry the shared embedded UoM plus its category name.
#: Named here as ``UomInfo`` because that is what this module's readers call
#: it; the definition lives in ``app.schemas.uom`` with the copy documents and
#: shopping lists embed, so the step a unit is counted in cannot drift
#: between them.
UomInfo = UomInfoWithCategory


class _QuantityAsNamed(BaseModel):
    """Keeps the quantity the client named beside the store's rounded one.

    The schema cuts ``quantity`` to the store's three places, and the unit's
    precision gate has to measure what the client actually said: a kilogram
    keeps three places too, so 1.1234 reached its gate as 1.123 — a number
    the kilogram can hold — and was written without a word. The gate reads
    ``quantity_as_named``; the store keeps ``quantity``, which is only ever
    written once the unit has let the named number through.
    """

    _quantity_as_named: Decimal | None = PrivateAttr(default=None)

    @model_validator(mode='wrap')
    @classmethod
    def _remember_quantity_as_named(cls, data, handler):
        model = handler(data)
        if isinstance(data, dict) and data.get('quantity') is not None:
            model._quantity_as_named = Decimal(decimal_from_int_float(data['quantity']))
        return model

    @property
    def quantity_as_named(self) -> Decimal | None:
        """The quantity before the store's rounding; ``quantity`` when unset."""
        if self._quantity_as_named is not None:
            return self._quantity_as_named
        quantity: Decimal | None = getattr(self, 'quantity', None)
        return quantity


class ItemBase(BaseModel):
    name: str
    brand: str | None = None
    description: str | None = None
    uom_id: UUID | None = None  # Logistics 2.0
    #: ``le`` mirrors the quantity column's shape (numeric(12, 3)) so the
    #: door answers an over-ceiling value with the bound named, not with
    #: the driver's overflow.
    quantity: Decimal = Field(default=Decimal('1.0'), ge=0, le=QUANTITY_MAX)
    barcode: str | None = None
    serial_number: str | None = None
    expiry_date: date | None = None
    freeze_date: date | None = None  # freeze date/date added to storage
    shelf_location: str | None = None
    metadata: dict[str, Any] | None = None

    # Conversion helpers (Logistics 2.0)
    weight_value: float | None = None
    weight_uom_id: UUID | None = None
    volume_value: float | None = None
    volume_uom_id: UUID | None = None

    # COST TRACKING
    purchase_price: Decimal | None = None
    currency: str | None = None

    @field_validator('barcode', mode='before')
    @classmethod
    def normalize_barcode_field(cls, v):
        return normalize_barcode(v)

    @field_validator(
        'brand',
        'shelf_location',
        'category_id',
        mode='before',
        check_fields=False,
    )
    @classmethod
    def empty_string_to_none_field(cls, v):
        return empty_string_to_none(v)

    @field_validator('expiry_date', 'freeze_date', mode='before')
    @classmethod
    def empty_string_date_to_none(cls, v):
        if v == '' or v is None:
            return None
        return v

    @field_validator('quantity', mode='before')
    @classmethod
    def to_decimal(cls, v):
        return decimal_from_int_float(v)

    @field_validator('quantity', mode='after')
    @classmethod
    def to_store_precision(cls, v):
        return quantize_quantity(v)


#: The unit a record lands with is its matched product template's, and that
#: column is the reference every other reader of the unit works from — the
#: BoM convertibility guard, the stock screen, the documents executor, which
#: converts a delivery into it rather than beside it. A caller that wants the
#: record kept in a different unit is making a deliberate choice: it has to
#: say so, and the choice is written into the record's history. The two
#: schemas below take the request; ``model_dump`` then carries a field the
#: ``items`` table has no column for, so each create/update turn pops it.
_UNIT_CONFIRMATION_FIELD = 'unit_confirmed_over_template'


def _take_unit_confirmation(update_data: dict[str, Any]) -> bool:
    """Pop the confirmation flag off the payload a caller is about to apply.

    Returns what the caller said, so the guard can tell a confirmed choice
    from a field nobody filled.
    """
    return bool(update_data.pop(_UNIT_CONFIRMATION_FIELD, False))


def _fold_meta_data_spelling(data: Any) -> Any:
    """Take ``meta_data`` on the way in, under the name the domain gave it.

    The request-side twin of :meth:`Item.map_meta_data_to_metadata`: one
    column, two spellings in the wild. The column, the module namespace
    convention and the core DTOs all say ``meta_data``; this schema's field
    has long been spelled ``metadata``. Pydantic drops an unknown key before
    any validator sees it, so the caller who followed the documented name got
    201 and a row without the payload — a quiet half-write at the API edge.

    A module namespace arriving here is a value, not a request to filter:
    ``meta_data`` is saved as sent and validated the same way a module's own
    write validates it (see ``core_api.items.update_meta_data_async``), which
    is what ``Item.module_name = resolve_module_owner(...)`` at create already
    presumes. It is not a whitelist of allowed namespaces — that gate exists
    for ``ProductTemplate.meta_data`` only.

    Both spellings at once is refused rather than won by one of them: the
    silent winner is the very loss being closed here.
    """
    if isinstance(data, BaseModel):
        return data
    try:
        payload = dict(data)
    except (TypeError, ValueError):
        return data
    if 'meta_data' not in payload:
        return data
    if 'metadata' in payload:
        raise ServiceRejectionError('meta_data_spelled_twice')
    payload['metadata'] = payload.pop('meta_data')
    return payload


class ItemCreate(_QuantityAsNamed, ItemBase):
    location_id: UUID
    category_id: UUID | None = None
    template_id: UUID | None = None
    image_url: str | None = None
    #: The receipt date of the goods, for a writer that knows it — a bulk
    #: import, or a split carrying stock off an older record. Left unset it
    #: stays the record's birth day (the column default); an explicit
    #: ``None`` means the same and is dropped before the row is built,
    #: because the column is NOT NULL.
    added_date: date | None = None
    #: ``True`` says the caller knows the unit it names differs from the
    #: matched product template's, and wants it anyway (AGENTS.md §4 —
    #: the template's unit is the reference; a different one is an explicit,
    #: recorded exception). Ignored when the two agree.
    unit_confirmed_over_template: bool = False
    #: A product-level field written to the card the record joins, exactly
    #: like ``weight_value`` above (ADR-015): the threshold is the product's,
    #: not the record's, so the card carries it for every record of it. It
    #: was read off the payload without ever being declared here, and
    #: Pydantic drops an unknown key before any validator sees it — a value
    #: the client named came back 201 and changed nothing (the same quiet
    #: half-write ``_fold_meta_data_spelling`` exists for).
    min_quantity: float | None = None
    #: The order the product's stock leaves in, written to the card like
    #: ``min_quantity``. Left unset, a card minted by this call takes its
    #: category's default; a card that already exists keeps its own.
    removal_strategy: RemovalStrategy | None = None
    #: The product's SKU, written to the card like ``min_quantity``. Left
    #: unset, a card minted by this call takes the next one of the
    #: organization's numbering, as before.
    sku: str | None = None

    @field_validator('sku', mode='before')
    @classmethod
    def normalize_sku_field(cls, v):
        return normalize_sku(v)

    @model_validator(mode='before')
    @classmethod
    def _accept_meta_data_spelling(cls, data):
        return _fold_meta_data_spelling(data)

    @field_validator('currency', mode='before')
    @classmethod
    def default_currency(cls, v):
        return v or None


class ItemUpdate(_QuantityAsNamed):
    name: str | None = None
    brand: str | None = None
    description: str | None = None
    uom_id: UUID | None = None  # Logistics 2.0
    quantity: Decimal | None = Field(default=None, ge=0, le=QUANTITY_MAX)
    barcode: str | None = None
    serial_number: str | None = None
    location_id: UUID | None = None
    #: See :data:`_UNIT_CONFIRMATION_FIELD`: the confirmation an update owes
    #: when it moves a record onto a unit its template does not keep.
    unit_confirmed_over_template: bool = False

    @field_validator('barcode', mode='before')
    @classmethod
    def normalize_barcode_field(cls, v):
        return normalize_barcode(v)

    expiry_date: date | None = None
    freeze_date: date | None = None  # freeze date/date added to storage
    shelf_location: str | None = None
    category_id: UUID | None = None
    metadata: dict[str, Any] | None = None
    image_url: str | None = None

    # COST TRACKING
    purchase_price: Decimal | None = None
    currency: str | None = None

    # Product-level fields, written to the item's template (ADR-015)
    min_quantity: float | None = None
    weight_value: float | None = None
    weight_uom_id: UUID | None = None
    removal_strategy: RemovalStrategy | None = None
    #: The product's SKU, changed on its card. ``None`` (or blank) clears it.
    sku: str | None = None

    @field_validator('sku', mode='before')
    @classmethod
    def normalize_sku_field(cls, v):
        return normalize_sku(v)

    @field_validator('quantity', mode='before')
    @classmethod
    def to_decimal(cls, v):
        return decimal_from_int_float(v)

    @field_validator('quantity', mode='after')
    @classmethod
    def to_store_precision(cls, v):
        return quantize_quantity(v)

    @model_validator(mode='before')
    @classmethod
    def _accept_meta_data_spelling(cls, data):
        return _fold_meta_data_spelling(data)


class ItemMove(BaseModel):
    to_location_id: UUID
    notes: str | None = None


class ItemQuantityUpdate(_QuantityAsNamed):
    #: No ``le`` here on purpose: this schema is the body of the quantity
    #: PATCH *and* the bridge a stock take's counted quantity travels —
    #: both carry client-named raw values, but bridges construct it from
    #: values their own doors have already parsed, where a pydantic
    #: refusal would be a defect's answer, not a sentence. The ceiling for
    #: every door through it stands on the writer,
    #: ``apply_quantity_change_async``.
    quantity: Decimal = Field(ge=0)

    @field_validator('quantity', mode='before')
    @classmethod
    def to_decimal(cls, v):
        return decimal_from_int_float(v)

    @field_validator('quantity', mode='after')
    @classmethod
    def to_store_precision(cls, v):
        return quantize_quantity(v)


class ItemImportMapping(BaseModel):
    name: str
    brand: str | None = None
    quantity: str | None = None
    expiry_date: str | None = None
    barcode: str | None = None
    location: str | None = None
    category: str | None = None
    purchase_price: str | None = None


class ItemImportResponse(BaseModel):
    """What one import did — including the org data it founded on the way.

    A sheet may name locations and categories the organization does not
    have yet; with auto-create on, the importer founds them. Their names
    travel back so the reader learns what the file added beside the
    products, instead of finding new tiles in the storage tree later.

    ``updated`` and ``skipped`` count the rows whose Label Code named a
    product the organization already had, under the update mode the reader
    chose; both stay zero when the import only adds.

    ``joined_existing`` counts the imported rows filed under a product that
    already existed — by its barcode, or by its name and brand — and so added
    stock to it rather than making a new product. A product two rows of one
    sheet make together counts its second row here.
    """

    total: int
    imported: int
    joined_existing: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int
    errors: list[dict] = []
    created_locations: list[str] = []
    created_categories: list[str] = []


class ItemImportJobResponse(BaseModel):
    """An import that runs on in the background, and how far it has got.

    A sheet too long for one request is answered with this (HTTP 202) and
    read again at ``GET /items/import/jobs/{id}`` until ``status`` is
    ``done`` — ``result`` then holds what the synchronous answer would have —
    or ``failed``, with ``error`` saying why.
    """

    id: UUID
    status: Literal['running', 'done', 'failed']
    total: int
    processed: int
    result: ItemImportResponse | None = None
    error: str | None = None


class Item(ItemBase):
    id: UUID
    location_id: UUID
    category_id: UUID | None = None
    template_id: UUID | None = None
    label_code: str | None = None
    added_date: date
    freeze_date: date | None = None  # freeze date/date added to storage
    image_url: str | None = None
    created_at: datetime
    updated_at: datetime
    category: Category | None = None
    template: ProductTemplate | None = None
    min_quantity: float | None = None  # from ProductTemplate via property
    # Total weight of the line, computed from the template's unit weight
    # (app.services.items.weight) — read-only, never stored on the item.
    weight: Decimal | None = None
    # Which unit `weight` is in: 'kg', or 'l' for items counted by volume.
    # Travels with the value so no reader has to assume kilograms.
    weight_unit: str | None = None
    uom: UomInfo | None = None  # Logistics 2.0 – embedded for frontend display
    source_document_id: UUID | None = None  # PZ/WZ/MM that created this item
    #: The use-by given when the package was opened, and the day the record is
    #: judged by — the earlier of that and the batch's ``expiry_date``. Both are
    #: read off the record, never sent in.
    use_by_date: date | None = None
    effective_expiry_date: date | None = None

    # SOFT DELETE fields (for archived items)
    is_deleted: bool = False
    deleted_at: datetime | None = None
    deleted_by: UUID | None = None
    deletion_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode='before')
    @classmethod
    def map_meta_data_to_metadata(cls, data):
        # Pydantic model instances (e.g. ItemDTO returned by the CoreAPI):
        # dump to a dict and normalize the embedded uom — UomDTO carries no
        # `category` relation, so build UomInfo from the flat fields instead
        # of calling from_orm_with_category (which used to raise AttributeError
        # and turn GET /locations/{id}/items into a 500).
        if isinstance(data, BaseModel):
            data_dict = data.model_dump()
            uom = data_dict.get('uom')
            if isinstance(uom, dict) and uom.get('id') is not None:
                # rounding comes across when the DTO carries it; the
                # schema default stands in when it does not, rather than
                # a precision invented here.
                step = uom.get('rounding')
                data_dict['uom'] = UomInfo(
                    id=uom['id'],
                    name=uom.get('name', ''),
                    symbol=uom.get('symbol', ''),
                    category_name='',
                    **({'rounding': step} if step is not None else {}),
                )
            if 'meta_data' in data_dict:
                data_dict['metadata'] = data_dict.pop('meta_data')
            elif 'metadata' not in data_dict:
                data_dict['metadata'] = None
            return data_dict
        # Handle SQLAlchemy model instances
        if hasattr(data, '__dict__') and 'meta_data' in data.__dict__:
            data_dict = data.__dict__.copy()
            # Surface freeze_date from meta_data['food'] (the Core column was
            # removed; the API field is preserved via a meta_data-backed shim).
            _food = (data_dict.get('meta_data') or {}).get('food') or {}
            if _food.get('freeze_date') is not None:
                data_dict['freeze_date'] = _food['freeze_date']
            data_dict['metadata'] = data_dict.pop('meta_data')
            # Populate uom from the relationship if available
            if hasattr(data, 'uom') and data.uom is not None:
                data_dict['uom'] = UomInfo.from_orm_with_category(data.uom)
            # Neither are synonyms: the column the API calls location_id
            # sits in __dict__ under its own name.
            data_dict['location_id'] = data.location_id
            # Python properties are not in __dict__, add them explicitly
            # (``image_url`` is built from the stored key the column keeps,
            # see app/core/file_reference.py, so the dict copy lacks it)
            data_dict['image_url'] = data.image_url
            if hasattr(data, 'min_quantity'):
                data_dict['min_quantity'] = data.min_quantity
            if hasattr(data, 'total_weight'):
                data_dict['weight'] = data.total_weight
            if hasattr(data, 'total_weight_unit'):
                data_dict['weight_unit'] = data.total_weight_unit
            return data_dict
        # Handle dict input
        elif isinstance(data, dict):
            if 'meta_data' in data:
                data['metadata'] = data.pop('meta_data')
            elif 'metadata' not in data:
                data['metadata'] = None
        return data

    @model_validator(mode='after')
    def fix_metadata_property(self):
        # Override the SQLAlchemy .metadata property with the actual meta_data value
        if hasattr(self, '__dict__') and 'meta_data' in self.__dict__:
            object.__setattr__(self, 'metadata', self.__dict__['meta_data'])
        self.use_by_date = use_by_of(self.metadata)
        self.effective_expiry_date = effective_expiry(self.expiry_date, self.metadata)
        return self


# New schemas for consume/discard actions
class ItemConsumeRequest(BaseModel):
    quantity: Decimal = Field(default=Decimal('1.0'), gt=0)
    reason: str | None = 'USED'
    notes: str | None = None

    @field_validator('quantity', mode='before')
    @classmethod
    def to_decimal(cls, v):
        return decimal_from_int_float(v)


class ItemUsePartiallyRequest(BaseModel):
    """What is left of a package, said in the unit the person sees on it.

    ``left`` absent only marks the package as opened. ``left_uom_id`` is the
    unit ``left`` is in — the weight or volume on the bag; without it the
    number is in the product's own unit (0.75 of a piece).
    """

    left: Decimal | None = Field(default=None, ge=0)
    left_uom_id: UUID | None = None
    #: Optional day after which the opened package should not be used. Sent
    #: as ``null`` it clears one; left out it changes nothing.
    use_by: date | None = None

    @field_validator('left', mode='before')
    @classmethod
    def to_decimal(cls, v):
        return decimal_from_int_float(v)


class ItemUseByRequest(BaseModel):
    """The use-by of an opened package: a date, or ``null`` to clear it."""

    use_by: date | None = None


class ItemDiscardRequest(BaseModel):
    quantity: Decimal = Field(default=Decimal('1.0'), gt=0)
    reason: str  # 'expired', 'damaged', 'lost'
    notes: str | None = None

    @field_validator('quantity', mode='before')
    @classmethod
    def to_decimal(cls, v):
        return decimal_from_int_float(v)


class ItemDeleteRequest(BaseModel):
    #: The reason the delete carried, when one was given. A delete that
    #: named none keeps none: the archive reads a missing reason as a lack
    #: (``ArchivedItemSheet`` says "Status: Unknown"), and defaulting this
    #: to ``OTHER`` had it claim an answer nobody gave — the two doors that
    #: never ask, the bulk confirmation and the swipe on the mobile card,
    #: both arrive without a body at all.
    reason: str | None = None
    notes: str | None = None


class ItemBulkUpdate(BaseModel):
    """Schema for bulk update operations."""

    item_ids: list[UUID]

    update_data: ItemUpdate


class ItemListResponse(PaginatedResponse[Item]):  # type: ignore[type-arg]
    """Paginated response for the items list endpoint.

    Concrete specialisation of PaginatedResponse[Item] — provides a stable
    named type for OpenAPI schema generation and frontend TypeScript codegen.
    Defaults maintained for backward compatibility.
    """

    limit: int = 100
    offset: int = 0
    has_more: bool = False


class ItemAggregates(BaseModel):
    """Totals over the whole filtered set, for the list footer.

    The list paginates server-side, so its sums cannot come from the rows on
    screen. ``weight`` is the ADR-015 derived line weight summed.
    ``total_volume`` is the same derivation's volume, in litres, summed
    apart from the kilograms — a litre is not a kilogram, and one figure
    labelled kilograms read 2 l of milk as 2 kg. A line counted in a volume
    unit lands in ``total_volume``, by the rule ``Item.total_weight_unit``
    applies per row. ``value`` is read where the statistics read it: from
    the cost ledger, each record at its product's layer-average rate, where
    the organization keeps one; from the price on each record where it does
    not. ``value_source`` says which, and ``unpriced_count`` how many of
    the counted rows the sum had nothing to price with. Rows without a
    weight count toward ``count`` only.

    The ledger answer exists only for the whole organization: its layers
    know products, not shelves, so a filtered request gets ``total_value``
    None and ``value_source`` ``not_available_under_filter`` — no figure,
    rather than one priced at rates the other shelves earned. A filter on
    a records-valued organization still gets its number, because there the
    price sits on the very rows the filter keeps.
    """

    count: int
    product_count: int
    total_weight: float
    total_volume: float
    total_value: float | None
    value_source: str
    unpriced_count: int
    #: True when the summed set leaves out the items a vertical module owns:
    #: the list's default view excludes them while the statistics tile sums
    #: the whole ledger, so the two figures differ by exactly those items —
    #: the footer says so instead of letting the reader find a discrepancy.
    excludes_module_items: bool = False
    #: True when the ledger holds open layers for products this list has no
    #: record of — the other reason the footer is below the statistics tile.
    excludes_unlisted_layers: bool = False


class AttentionCounts(BaseModel):
    """How much of the stock needs a hand — one number per rule.

    ``expired`` and ``expiring_soon`` count records on internal shelves;
    ``low_stock`` counts short products, because the threshold belongs to
    the product (see ``app.services.items.low_stock``). The dashboard
    heading and the statistics health card both read these three numbers
    from the same service, so the two screens cannot disagree about what
    needs attention.

    ``records`` is the number a reader follows: the rows the "needs
    attention" list opens with. It is not the sum of the three, whose units
    differ.
    """

    expired: int
    expiring_soon: int
    low_stock: int
    records: int


class ArchivedCategoryBrief(BaseModel):
    id: UUID
    name: str
    #: The seed code, when this category has one — the reader's language
    #: names the category through it, and the record name is the fallback.
    code: str | None = None
    icon: str | None = None


class ArchivedItemSchema(BaseModel):
    id: UUID
    name: str
    location_id: UUID
    category_id: UUID | None = None
    quantity: Decimal = Decimal('0')
    purchase_price: Decimal | None = None
    currency: str | None = None
    is_deleted: bool = True
    deleted_at: datetime | None = None
    deleted_by: UUID | None = None
    deletion_reason: str | None = None
    category: ArchivedCategoryBrief | None = None


class ArchivedItemListResponse(PaginatedResponse[ArchivedItemSchema]):  # type: ignore[type-arg]
    """Paginated response for the archived items list endpoint."""

    limit: int = 50
    offset: int = 0
    has_more: bool = False
