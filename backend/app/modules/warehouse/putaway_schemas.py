"""Pydantic schemas for PutawayRule CRUD."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.exceptions import ServiceRejectionError


class PutawayRuleCreate(BaseModel):
    """At least one match key and one target shelf must be set.

    ``location_ids`` is the rule's ordered list — the resolver walks it in
    order, first fit wins. ``target_location_id`` still works and reads as
    a list of one, so existing callers keep speaking the old shape; it is
    the deprecated spelling.
    """

    product_template_id: UUID | None = None
    category_id: UUID | None = None
    context_tag: str | None = Field(default=None, max_length=100)
    location_type_code: str | None = Field(default=None, max_length=50)
    location_ids: list[UUID] = Field(default_factory=list)
    target_location_id: UUID | None = None
    priority: int = Field(default=100, ge=0)
    is_active: bool = True

    @model_validator(mode='after')
    def _locations_present(self) -> PutawayRuleCreate:
        if not self.location_ids and self.target_location_id is None:
            raise ValueError('Provide location_ids (ordered) or target_location_id.')
        if len(set(self.location_ids)) != len(self.location_ids):
            raise ValueError('location_ids must not repeat a location.')
        return self

    @model_validator(mode='after')
    def _at_least_one_match(self) -> PutawayRuleCreate:
        if (
            self.product_template_id is None
            and self.category_id is None
            and not self.context_tag
            and not self.location_type_code
        ):
            raise ValueError(
                'At least one of product_template_id, category_id, '
                'context_tag, storage_type_code must be set.'
            )
        return self


class PutawayRuleUpdate(BaseModel):
    product_template_id: UUID | None | None = None
    category_id: UUID | None | None = None
    context_tag: str | None | None = Field(default=None, max_length=100)
    location_type_code: str | None | None = Field(default=None, max_length=50)
    # Replaces the whole ordered list when present; an empty list is a
    # refusal, not a clearing — a rule without a shelf points nowhere.
    location_ids: list[UUID] | None = None
    target_location_id: UUID | None = None
    priority: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class PutawayRuleLocationOut(BaseModel):
    """One shelf on a rule's ordered list, with its live state."""

    location_id: UUID
    position: int
    location_name: str | None = None
    # False when the shelf cannot take goods right now — archived, or one
    # of the virtual counterparts. The resolver skips such a shelf.
    active: bool = True

    model_config = ConfigDict(from_attributes=True)


class PutawayRuleOut(BaseModel):
    id: UUID
    organization_id: UUID
    product_template_id: UUID | None
    category_id: UUID | None
    context_tag: str | None
    location_type_code: str | None
    # The head of the rule's ordered list; None only if a rule somehow has
    # no shelves, which creation refuses.
    target_location_id: UUID | None = None
    # The rule's ordered shelf list, resolved by the router with names and
    # live states. ``target_location_*`` above mirror the head of the list.
    locations: list[PutawayRuleLocationOut] = Field(default_factory=list)
    priority: int
    is_active: bool
    created_at: datetime
    # Read-only display names resolved by the router (not stored columns).
    product_template_name: str | None = None
    category_name: str | None = None
    target_location_name: str | None = None
    # Resolved by the router with the same read that resolves the name:
    # False when the target cannot take goods right now — archived, or one
    # of the virtual counterparts. The rules list marks such rules instead
    # of letting them read as ordinary, working ones.
    target_location_active: bool = True

    model_config = ConfigDict(from_attributes=True)


class PutawayCapacityCreate(BaseModel):
    """One shelf's limit for one product, in the product's stock unit."""

    location_id: UUID
    product_template_id: UUID
    max_quantity: Decimal = Field(gt=0)


class PutawayCapacityUpdate(BaseModel):
    """Only the number moves; shelf and product are the entry's identity."""

    max_quantity: Decimal = Field(gt=0)


class PutawayCapacityOut(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID
    product_template_id: UUID
    max_quantity: Decimal
    # Read-only, resolved by the router for a reader without UUIDs.
    location_name: str | None = None
    product_template_name: str | None = None
    # The limit speaks the product's stock unit; the symbol rides along so
    # the screen can say "10 kg" instead of a bare number that reads the
    # same for pieces. None when the template carries no unit.
    product_unit_symbol: str | None = None
    # The replenishment side of the same (location, product) pair, read at
    # response time: when the rule wants more than the shelf holds, the
    # warning rides along instead of the two numbers disagreeing in
    # silence. Absent rule → null and False.
    reorder_max_quantity: Decimal | None = None
    reorder_over_capacity: bool = False

    model_config = ConfigDict(from_attributes=True)


class PutawayLocationSettingOut(BaseModel):
    """A location's product mix. Absent row reads mixed — the default."""

    location_id: UUID
    single_product: bool = False

    model_config = ConfigDict(from_attributes=True)


class PutawayLocationSettingUpdate(BaseModel):
    single_product: bool


class WarehouseReceivingOut(BaseModel):
    """How one warehouse receives. A warehouse with no row receives in one step."""

    warehouse_id: UUID
    two_step: bool
    #: True when the warehouse stores goods wherever there is room: put-away
    #: never asks whether a shelf is a product's home there.
    free_placement: bool = False
    #: Where its two-step receipts land; kept after switching back to one
    #: step, while goods may still wait there.
    receiving_location_id: UUID | None = None
    receiving_location_name: str | None = None


class WarehouseReceivingUpdate(BaseModel):
    """The choices sent are changed; the ones left out stay as they were."""

    two_step: bool | None = None
    free_placement: bool | None = None

    @model_validator(mode='after')
    def _something_to_change(self) -> WarehouseReceivingUpdate:
        if self.two_step is None and self.free_placement is None:
            raise ServiceRejectionError('no_fields_to_update')
        return self


class PutawayOccupancyEntry(BaseModel):
    """One product on a shelf: what stands there against its limit.

    Quantities speak the product's stock unit — the same unit the limit
    was declared in, so the two compare without a conversion. ``share`` is
    the product's part of the shelf in percent; the shelf's fill is the sum
    of them. A product without a limit here has neither a limit nor a
    share: it is unmeasured, not zero.
    """

    product_template_id: UUID
    product_template_name: str | None = None
    product_unit_symbol: str | None = None
    quantity: Decimal
    max_quantity: Decimal | None
    share: int | None


class PutawayOccupancyCell(BaseModel):
    """One shelf in the occupancy grid.

    ``fill`` is the shelf's fill in percent: the sum of every limited
    product's share, the same sum the putaway planner decides by.
    ``status`` reads it as ``empty`` / ``no_limit`` / ``ok`` /
    ``nearly_full`` (from 85%) / ``over``; ``unmeasured`` says a product
    stands here without a limit, so part of the shelf is not counted.
    ``capacity_used`` / ``capacity_max`` are the pair of the product taking
    the largest share, and ``capacity_product_name`` says whose. All of
    them are null on a shelf nobody limited — such a cell shows
    ``items_count`` instead of a percentage.

    ``entries`` lists every product on the shelf in the read of one
    location. The overview of the whole floor lists the limited products
    only — the segments of the bar — and the one product of a shelf that
    holds one; ``products`` counts them all, and the reader asks the
    location's own read for the rest.
    """

    # No defaults: every cell carries all of these, and a default would
    # make the generated type optional where the wire never omits it —
    # forcing the reader into `?? []` guards against a case that cannot
    # happen. Null, where it appears, is the meaningful answer: no limit.
    location_id: UUID
    location_name: str | None
    entries: list[PutawayOccupancyEntry]
    capacity_product_name: str | None
    capacity_used: Decimal | None
    capacity_max: Decimal | None
    capped_products: int
    #: Products standing on the shelf, whether ``entries`` lists them or not.
    products: int
    fill: int | None
    status: Literal['empty', 'no_limit', 'ok', 'nearly_full', 'over']
    unmeasured: bool
    items_count: int


class PutawayOccupancySignal(BaseModel):
    """A sentence the company overview quotes.

    Two shapes behind one code field: a shelf that is nearly full names the
    shelf and its fill; the count of receipt lines with nowhere to go names
    only a count. The unused half stays null rather than becoming a second
    endpoint.
    """

    code: str
    location_id: UUID | None = None
    location_name: str | None = None
    fill: int | None = None
    count: int | None = None


class PutawayOccupancyOut(BaseModel):
    """The occupancy read: every shelf under one location, and the signals."""

    locations: list[PutawayOccupancyCell]
    signals: list[PutawayOccupancySignal]


class PutawayPreviewLineIn(BaseModel):
    """One line of a receipt the receive screen has not saved yet.

    The fields mirror what the executor reads off a document line: the
    record (or catalogue product), the quantity in the unit it was stated
    in, and the shelf the worker named over the plan.
    """

    item_id: UUID | None = None
    product_template_id: UUID | None = None
    quantity: Decimal = Field(ge=0)
    uom_id: UUID | None = None
    target_location_id: UUID | None = None


class PutawayPreviewRequest(BaseModel):
    """Where a delivery is going, and the lines it brings.

    ``target_location_id`` is the document's destination — the shelf a rule
    loses to and the one an unruled line lands on.
    """

    target_location_id: UUID
    lines: list[PutawayPreviewLineIn] = Field(min_length=1, max_length=500)


class PutawayPreviewLineOut(BaseModel):
    """Where one unsaved line will land, and who decided.

    Named exactly as ``DocumentLine``'s plan fields so the same sentence
    component and the same reading rule serve the saved document and the
    form being filled in.
    """

    planned_location_id: UUID | None = None
    planned_location_name: str | None = None
    planned_source: str
    planned_rule_match_key: str | None = None
    planned_rule_match_name: str | None = None
    planned_rule_warning: str | None = None
    planned_over_capacity: bool = False
    planned_capacity_used: Decimal | None = None
    planned_capacity_max: Decimal | None = None
    planned_shelf_fill: int | None = None


class PutawayOccupancySummary(BaseModel):
    """What a location holds, counted over the shelves under it.

    ``average_fill`` is taken over the shelves with a limit only — a shelf
    nobody limited has no fill, and counting it as zero would make a
    warehouse of unlimited shelves look empty. A shelf past its limit counts
    as 100% there, so one overflow does not hide ten shelves with room.
    ``full`` includes the shelves over their limit.
    """

    shelves: int
    with_limit: int
    full: int
    over: int
    empty: int
    average_fill: int | None


class PutawayOccupancyNode(BaseModel):
    """One location of the occupancy tree, in walk order.

    The list is depth first and each parent stands before its children, so a
    reader folds a branch by skipping the rows deeper than it. ``cell`` is set
    on a shelf (a location with nothing under it, or one that holds stock or
    a limit itself); ``summary`` on a location that has others under it.
    """

    location_id: UUID
    parent_id: UUID | None
    name: str
    short_code: str | None
    sequence: int | None
    depth: int
    has_children: bool
    cell: PutawayOccupancyCell | None
    summary: PutawayOccupancySummary | None


class PutawayOccupancyOverview(BaseModel):
    """Every warehouse and shelf of the organization in one answer.

    The cells carry their fill, not their contents: a floor of two thousand
    shelves holds hundreds of thousands of product groups, and sending them
    all made the answer tens of megabytes and tens of seconds.
    """

    nodes: list[PutawayOccupancyNode]
    totals: PutawayOccupancySummary


class HomeShelfOffer(BaseModel):
    """What a put-away says about the shelf the goods were put on.

    ``set``: the product has no home shelf and this one is offered. ``change``:
    it has another and this one is offered in its place. ``refused``: this
    shelf cannot be a home, and ``reason`` (``receiving``, ``quarantine`` or
    ``not_stock``) says why.
    """

    kind: Literal['set', 'change', 'refused']
    reason: Literal['receiving', 'quarantine', 'not_stock'] | None = None
    product_template_id: UUID
    product_name: str | None = None
    location_id: UUID
    location_name: str | None = None


class HomeShelfSet(BaseModel):
    """The product and the shelf that becomes its home."""

    product_template_id: UUID
    location_id: UUID


class HomeShelfOut(BaseModel):
    """The rule that now holds the product's home shelf, first on its list."""

    rule_id: UUID
    product_template_id: UUID
    location_id: UUID


class HomeShelfSilencedOut(BaseModel):
    """A product whose put-away does not ask for a home shelf."""

    product_template_id: UUID
    product_name: str | None = None
