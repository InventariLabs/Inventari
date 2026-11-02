from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StockQuantDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    product_template_id: UUID
    location_id: UUID
    lot_id: UUID | None = None
    owner_id: UUID | None = None
    quantity: Decimal = Decimal('0')
    reserved_quantity: Decimal = Decimal('0')
    removal_strategy: str = 'FIFO'
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def available_quantity(self) -> Decimal:
        return self.quantity - self.reserved_quantity


class ShelfContentsDTO(BaseModel):
    """What stands on one shelf, told the way a map of a whole floor needs it.

    A floor of two thousand shelves holds hundreds of thousands of product
    groups, and a reader that draws one tile per shelf needs three things of
    each, not the groups themselves: how many products stand there, which one
    when it is one, and the quantities of the products it asked about.
    """

    location_id: UUID
    #: Products with stock on the shelf (a positive quantity).
    products: int
    #: The product, when exactly one stands there, and its quantity.
    only_product_template_id: UUID | None = None
    only_quantity: Decimal | None = None
    #: Each product the caller named that the shelf holds records of, summed
    #: whatever the sign: a limit is weighed against what is there.
    quantities: dict[UUID, Decimal] = {}


class StockQuantRowDTO(BaseModel):
    """A shelf as a person reads it, not as five identifiers.

    Deliberately not a subclass of :class:`StockQuantDTO`: that one carries
    ``available_quantity`` as a Python property, which a response model does
    not serialise, and the whole point of this row is that the promise is a
    column of its own.

    The names are read in the same statement as the row — resolving them per
    row would cost four lookups a row on a page of five hundred.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_template_id: UUID
    location_id: UUID
    lot_id: UUID | None = None
    quantity: Decimal = Decimal('0')
    reserved_quantity: Decimal = Decimal('0')
    #: Stock minus reservations, computed once here so every reader agrees.
    available_quantity: Decimal = Decimal('0')
    product_name: str | None = None
    uom_symbol: str | None = None
    location_name: str | None = None
    lot_name: str | None = None
    #: Why a picker may not touch it — a recalled batch is invisible on the
    #: shelf otherwise, and the refusal only arrives at picking time.
    lot_status: str | None = None
    #: The earliest date by which the goods of this row should be used: what
    #: its records say (an opened package's use-by included), else its batch's.
    expiry_date: date | None = None


class PickGroupDTO(BaseModel):
    """The group and the lot a picking line plans from.

    Picking names a shelf with a product on it (the group: organization,
    product, shelf — the row ``stock_anchors`` locks) and the batch the
    picker is to take, not a row of the quant table. ``anchor_id`` is
    ``None`` for a group nothing has stocked yet, and the lot is
    ``None`` for stock that carries no batch: both stay ``None`` on a
    line planned against an empty shelf.
    """

    model_config = ConfigDict(from_attributes=True)

    anchor_id: UUID | None = None
    product_template_id: UUID
    location_id: UUID
    lot_id: UUID | None = None
    owner_id: UUID | None = None
    #: The date of what a draw takes first from this group: the batch's, or
    #: the record's own for stock with no batch.
    expiry_date: date | None = None


class LotStatus(StrEnum):
    """Status values for ``StockLotDTO.status`` / ``StockLot.status``.

    Only ``ACTIVE`` stock may be consumed, reserved or picked. Every other
    value means the goods physically exist but are operationally held.

    Lives here rather than in ``app.models`` so that modules — which the
    import lint keeps out of ``app.models`` — can name the values of a field
    the contract already hands them. Re-exported from
    ``app.models.stock_lot`` for callers on that import path.
    """

    ACTIVE = 'active'
    QUARANTINED = 'quarantined'
    HELD = 'held'
    EXPIRED = 'expired'
    RECALLED = 'recalled'


class StockLotDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    product_template_id: UUID
    name: str
    is_serial: bool = False
    expiry_date: date | None = None
    production_date: date | None = None
    use_by_date: date | None = None
    removal_strategy: str = 'FIFO'
    status: str = 'active'
    #: Why the batch is in that state — read from the status history, and
    #: only when the newest entry is about the state the batch is in now.
    #: A status without one is a decision nobody can review.
    status_reason: str | None = None
    meta_data: dict[str, Any] | None = None
    created_at: datetime | None = None


class QuantConsumptionDTO(BaseModel):
    """How much a draw or a movement took off one grain of stock.

    The grain is a batch, on a shelf, of an owner. A draw on every shelf of
    a product (a production run) says where each part came from and whose
    goods it was, because the caller has to be able to answer both.
    """

    lot_id: UUID | None = None
    consumed: Decimal
    location_id: UUID | None = None
    owner_id: UUID | None = None
    #: Set on stock that carries no batch: the date its records were
    #: received with. A batch's date is the batch's.
    expiry_date: date | None = None
    # Set by a plan read record by record (``plan_draw_async`` with
    # ``by_record``): the stock record that gives this part. A draw that
    # took stock with no batch names the first record of each date.
    record_id: UUID | None = None


class RecordPostDTO(BaseModel):
    """One record a stock movement is, and the number it says afterwards.

    Handed to ``core_api.stock.post_movement_async`` by the door that knows
    the record: the number was read under the record's own lock, and the
    write lands inside the movement's anchor locks, beside the movement —
    one operation, one transition of the pair (record,
    ledger), not the record changed by the door and the ledger settled by
    the service afterwards.
    """

    item_id: UUID
    new_quantity: Decimal
    history: dict[str, Any] | None = None
    source_document_id: UUID | None = None


class ItemHistoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID | None = None
    item_id: UUID
    user_id: UUID | None = None
    action: str
    changes: dict[str, Any] | None = None
    source_document_id: UUID | None = None
    created_at: datetime | None = None


class StockMoveState(StrEnum):
    """Lifecycle value for ``StockMoveDTO.state`` / ``StockMove.state``.

    One value exists: every writer lands a row directly at ``DONE`` —
    receipts, deliveries, manual quantity edits, stock-take corrections,
    production. Nothing transitions the column; the other lifecycle
    names were declared and never implemented, so they are not declared
    here anymore.

    Lives here rather than in ``app.models`` so that modules — which the
    import lint keeps out of ``app.models`` — can name the values of a
    field the contract already hands them. Re-exported from
    ``app.models.stock_move`` for callers on that import path.
    """

    DONE = 'done'


class StockMoveReferenceType(StrEnum):
    """Values written to ``StockMoveDTO.reference_type``.

    The column is free-form (no DB enum, no FK); this enum documents
    what actually lands there, and nothing else is declared:

      - ``document``        — document execution (receipt/delivery lines)
      - ``item``            — direct ``Item.quantity`` edit via
        ``_post_the_change_async``
      - ``adjustment``      — stock-take correction
      - ``maker_production``— maker production consumption and output
      - ``recipe_picking``  — ingredients taken for cooking, and put back when
        a pick is undone or the cooking called off (``reference_id`` is the
        picking session)
      - ``item_history``    — one-time backfill from ItemHistory rows
      - ``opening_balance`` — the stock a shelf held before the register knew
        it, posted once by the ``openbal01`` migration and since by every door
        that adopts a card for a record that predates one
        (``reference_id`` is then that record)
      - ``location_relocation`` — a location that physically moved with the
        stock inside it: one movement per product, the shelf on both ends,
        quantity unchanged (``reference_id`` is the ``LocationRelocation``,
        which names the path it left and the path it reached)

    These strings are a contract, not an internal label: the moves
    register shows the value's translation in its SOURCE column, and rows
    carrying every one of them are already in the field. So a value here
    is renamed only with a data migration, and the frontend follows this
    list rather than the other way round — adding one without a label in
    ``frontend/src/modules/inventory/i18n`` fails
    ``moveSourceVocabulary.test.ts``, which reads this class here in the
    contracts rather than in the model, where it used to sit.

    Re-exported from ``app.models.stock_move`` for callers on that import
    path.
    """

    DOCUMENT = 'document'
    ITEM = 'item'
    ADJUSTMENT = 'adjustment'
    MAKER_PRODUCTION = 'maker_production'
    RECIPE_PICKING = 'recipe_picking'
    ITEM_HISTORY = 'item_history'
    OPENING_BALANCE = 'opening_balance'
    LOCATION_RELOCATION = 'location_relocation'


class StockMoveDTO(BaseModel):
    """Explicit WMS stock movement record (analytics + traceability)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    product_template_id: UUID
    from_location_id: UUID | None = None
    to_location_id: UUID | None = None
    quantity: Decimal
    lot_id: UUID | None = None
    #: The partner whose goods moved (consignment), or NULL for the
    #: organization's own. The line posts one record per batch and owner, so
    #: a group of stock is named by all four of product, shelf, batch and
    #: owner — a reader comparing one group must see this one too.
    owner_id: UUID | None = None
    #: The date of the goods that left, as the draw ranked them.
    expiry_date: date | None = None
    state: str
    reference_type: str | None = None
    reference_id: UUID | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None


class StockMoveRowDTO(StockMoveDTO):
    """A movement as a person reads it, not as five identifiers.

    The names are read in the same statement as the row (see
    ``stock_moves_service.list_rows_for_org_async``): resolving them per row
    would cost five lookups a row on a page of up to five hundred.

    Every one of them is optional because the movement it describes may not
    have that end at all — a delivery from outside has no origin, a product
    without batches has no batch, and a row written by a background path has
    nobody's name on it. What the source *is* stays ``reference_type`` and
    ``reference_id``: naming a document means reading a table Core must not
    import.
    """

    product_name: str | None = None
    uom_symbol: str | None = None
    from_location_name: str | None = None
    to_location_name: str | None = None
    lot_name: str | None = None
    user_name: str | None = None
    #: A movement of a location that physically moved (``reference_type``
    #: ``location_relocation``): its name and the paths it left and reached,
    #: which the shelf on both ends of the row cannot say.
    relocated_location_name: str | None = None
    relocated_from_path: str | None = None
    relocated_to_path: str | None = None


class StockMovePostedGroupDTO(BaseModel):
    """One group of stock a source filled, and when it last filled it.

    A movement says what landed where: the product, the shelf it landed on,
    the batch and the owner. Those four together are a group of stock, and a
    later movement has to leave from that same group to have used the goods.
    One source may fill the same group more than once, so this is the
    ledger's reading of a source — one row per group, not per movement.

    ``posted_at`` is the moment the last row landed in the group, which is
    the clock a later departure is compared against. The read is not a page:
    a caller asking whether the stock a document posted has since been used
    has to see every group, because a finite sample drops the oldest group
    whole — and the oldest goods are the ones most likely to have moved on.
    """

    product_template_id: UUID
    to_location_id: UUID
    lot_id: UUID | None = None
    owner_id: UUID | None = None
    posted_at: datetime


class LotLocationDTO(BaseModel):
    """How much of one batch is standing in one place."""

    model_config = ConfigDict(from_attributes=True)

    location_id: UUID
    location_name: str | None = None
    quantity: Decimal = Decimal('0')
    reserved_quantity: Decimal = Decimal('0')


class LotStatusEventDTO(BaseModel):
    """One decision about a batch, as a person reads it.

    The entry in ``meta_data['status_history']`` stores the author as a bare
    UUID and the moment as an ISO string; the reader gets the name resolved
    and the moment typed.
    """

    status: str
    reason: str | None = None
    at: datetime | None = None
    by_name: str | None = None


class StockLotDetailDTO(StockLotDTO):
    """A batch with the two things a recall asks for beyond its own fields.

    ``on_hand`` and ``locations`` come from the records, not from replaying
    the ledger: the shelf is its own record, and the point of putting the
    two next to each other is that a reader can see whether they agree.
    """

    product_name: str | None = None
    uom_symbol: str | None = None
    on_hand: Decimal = Decimal('0')
    locations: list[LotLocationDTO] = []
    #: The decisions the batch went through, newest first — the quarantine
    #: with its reason, author and day that the ledger of movements never
    #: held.
    status_history: list[LotStatusEventDTO] = []


class StockAsOfRowDTO(BaseModel):
    """One product, as it stood on a given day."""

    model_config = ConfigDict(from_attributes=True)

    product_template_id: UUID
    product_name: str | None = None
    uom_symbol: str | None = None
    quantity: Decimal = Decimal('0')
    #: None where the organization keeps no cost history — see the report.
    value: Decimal | None = None


class StockAsOfReportDTO(BaseModel):
    """What the warehouse held on a date, and what it was worth.

    ``complete_from`` is the boundary the ledger can answer from — the
    oldest movement it holds. A date before it is refused rather than
    answered: calm numbers for a year nothing was recorded in are more
    dangerous than a refusal.
    """

    model_config = ConfigDict(from_attributes=True)

    as_of: datetime
    generated_at: datetime
    complete_from: datetime
    organization_name: str | None = None
    currency: str | None = None
    #: ``valuation_layers`` — the same name every other value report uses
    #: for the ledger — where the organization posts layers, else None.
    #: Never ``purchase_price``: that is a field on a form today and cannot
    #: say what a shelf was worth last month.
    value_source: str | None = None
    #: Rows left out of the total because their currency is not the
    #: organization's — two currencies do not add.
    excluded_currency_rows: int = 0
    #: The value of every row, whichever page ``items`` holds.
    total_value: Decimal | None = None
    #: One page of the rows, in name order: ``limit`` of them from
    #: ``offset``, out of ``total``. The files carry every row.
    items: list[StockAsOfRowDTO] = []
    total: int = 0
    limit: int | None = None
    offset: int = 0
    has_more: bool = False
    #: Rows whose value nobody can state, counted over every row.
    unpriced: int = 0


class StockAgeEntryDTO(BaseModel):
    """One receipt entry — a single StockMove for a product, with age.

    Built from StockMove rows where ``from_location_id IS NULL``
    (external receipts) so the aging report is per-receipt rather
    than per-current-quant.  ``days_in_stock`` is computed at query
    time, not stored.
    """

    model_config = ConfigDict(from_attributes=True)

    move_id: UUID
    received_at: datetime
    quantity: Decimal
    location_id: UUID | None = None
    lot_id: UUID | None = None
    reference_type: str | None = None
    days_in_stock: int


class StockAgeBucketDTO(BaseModel):
    """Aggregated bucket of stock by age range (for aging reports).

    Open-ended upper bound (e.g. ``180+``) is represented by
    ``max_days=None``.
    """

    model_config = ConfigDict(from_attributes=True)

    label: str
    min_days: int
    max_days: int | None = None
    quantity: Decimal
    move_count: int


class ReservedSliceDTO(BaseModel):
    """One slice a reservation locked: its lot, its owner, its quantity.

    The row that records it is the reservation's own id, so a caller that
    has to give a hold back — or say which hold it means — names the row
    and never the quant the hold used to point at. ``reservation_id`` is
    ``None`` when the reservation was made without a document, because
    then no row exists to name.
    """

    reservation_id: UUID | None = None
    lot_id: UUID | None = None
    owner_id: UUID | None = None
    quantity: Decimal


class ReservationResultDTO(BaseModel):
    """Outcome of an atomic stock reservation attempt.

    ``reserved`` holds one :class:`ReservedSliceDTO` per slice the
    reservation locked — lot, owner, quantity and the row that records
    it; ``unreserved_quantity`` is the shortfall when the request could
    not be fully satisfied.
    """

    reserved: list[ReservedSliceDTO] = Field(default_factory=list)
    unreserved_quantity: Decimal = Decimal('0')
    success: bool = True
    message: str = ''


class ReservationDTO(BaseModel):
    """Per-document stock reservation record.

    Named by lot and owner, the way the stock it holds is counted, and by
    its own row id. The quant it used to point at is gone from the
    contract: after the record migration nothing reads one, and a
    contract that named it would keep the id alive in every caller.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    document_id: UUID
    document_line_id: UUID | None = None
    product_template_id: UUID | None = None
    location_id: UUID | None = None
    lot_id: UUID | None = None
    owner_id: UUID | None = None
    quantity: Decimal
    created_at: datetime | None = None


class DocumentReservationHoldDTO(BaseModel):
    """What one document holds at one product on one shelf, as a sum.

    The reservations a document owns are several rows whenever it held the
    same group twice; this is one row per (document, product, shelf), which
    is the grain a screen shows a hold at. The product, the shelf and the
    unit come with the row — read in the same statement, because resolving
    them per row would be three lookups per hold across a screen of held
    documents.

    The document's own number and date are not here: the document table
    belongs to the module that owns the document, and this contract stays
    on the stock side of the join.
    """

    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    product_template_id: UUID
    location_id: UUID
    quantity: Decimal
    product_name: str
    uom_symbol: str | None = None
    location_name: str
