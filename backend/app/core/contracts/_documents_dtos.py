from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ShoppingListDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    created_by: UUID
    created_at: datetime | None = None


class ShoppingListItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    shopping_list_id: UUID
    name: str
    quantity: Decimal
    uom_id: UUID | None = None
    notes: str | None = None
    note_data: dict[str, Any] | None = None
    estimated_price: Decimal | None = None
    priority: int = 0
    template_id: UUID | None = None
    source: str = 'manual'
    item_id: UUID | None = None
    category_id: UUID | None = None
    is_purchased: bool = False


class ShoppingListItemCreateDTO(BaseModel):
    """Contract DTO for adding items to a shopping list.

    Used by modules (e.g., recipes) via CoreAPI to avoid importing
    from ``app.modules.shopping_lists.schemas`` directly.
    """

    name: str
    quantity: Decimal = Field(default=Decimal(1), gt=0)
    uom_id: UUID | None = None
    notes: str | None = None
    note_data: dict[str, Any] | None = None
    """Structured note parts (needed_by, check_stock, matched_by_name) a
    service composed; the interface re-renders them in the reader's language.
    `notes` stays the composed-at-generation fallback."""
    estimated_price: Decimal | None = None
    priority: int = Field(default=0, ge=0, le=2)
    source: str = 'manual'
    item_id: UUID | None = None
    category_id: UUID | None = None
    template_id: UUID | None = None


class ReceiptLineFromPODTO(BaseModel):
    """Contract DTO for creating a receipt (IN document) from a Purchase Order.

    Used by the purchase_orders module via CoreAPI to avoid importing
    from ``app.modules.warehouse.schemas`` directly.
    """

    product_template_id: UUID | None = None
    name: str | None = None
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    uom_id: UUID | None = None
    tax_rate: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    notes: str | None = None
    source_po_line_id: UUID | None = None


class ReorderRuleDTO(BaseModel):
    """Per-location reorder threshold (purchase_orders module).

    See ``app.modules.purchase_orders.models.ReorderRule`` for the
    underlying table.  Exposed via ``core_api.purchase_orders.*``.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    product_template_id: UUID
    location_id: UUID
    min_quantity: Decimal
    max_quantity: Decimal
    safety_stock: Decimal
    preferred_partner_id: UUID | None = None
    notes: str | None = None


class ReplenishmentAlertDTO(BaseModel):
    """Stock-shortage alert for one (product, location) reorder rule.

    Produced by ``purchase_orders.replenishment_service`` and exposed to
    the documents stock router via ``purchase_orders_api`` so callers
    never import internal module code. Mirrors the alert dict that the
    UI consumed before this DTO existed.
    """

    reorder_rule_id: UUID
    product_template_id: UUID
    product_name: str
    sku: str
    location_id: UUID
    #: Free stock at the rule's location plus what transfers have already
    #: promised into it — goods on their way are not a shortage to buy for.
    available_quantity: float
    min_quantity: float
    max_quantity: float
    safety_stock: float
    shortage: float
    suggested_reorder_quantity: float
    #: What the product has on reserve locations of the same warehouse, free
    #: to be carried to a pick face (unreserved, active batches only). The
    #: pool is shared with the product's other alerts, so it is not all this
    #: rule's to count on — ``remaining_to_buy`` carries that part.
    reserve_available_quantity: float = 0
    #: What the proposal would carry off the reserve shelf, at most
    #: ``suggested_reorder_quantity``, at most this rule's share of the
    #: warehouse's reserve (shared with the product's other alerts), and at
    #: most what that one shelf holds.
    proposed_move_quantity: float = 0
    #: The part of ``suggested_reorder_quantity`` this rule's share of
    #: reserve cannot cover — the quantity a draft purchase order is for.
    remaining_to_buy: float | None = None
    # The rule's preferred supplier, when set — the alerts view marks an
    # alert without one as "no supplier" instead of offering a draft PO.
    preferred_partner_id: UUID | None = None
    preferred_partner_name: str | None = None


class ReplenishmentMoveLineDTO(BaseModel):
    """One record a reserve replenishment would carry to a pick face.

    The proposal is read by the warehouse module's To do action through
    ``purchase_orders_api``: it names the stock records, their shelf and
    batch, so the transfer can be opened with its lines already prepared.
    """

    item_id: UUID
    product_template_id: UUID
    product_name: str
    lot_id: UUID | None = None
    lot_name: str | None = None
    expiry_date: date | None = None
    source_location_id: UUID
    source_location_name: str
    quantity: Decimal
    uom_id: UUID | None = None
    uom_symbol: str | None = None


class ReplenishmentProposalDTO(BaseModel):
    """The internal move an alert proposes: what, from where, and how much."""

    reorder_rule_id: UUID
    product_template_id: UUID
    product_name: str
    target_location_id: UUID
    target_location_name: str
    quantity: Decimal
    unit: str | None = None
    lines: list[ReplenishmentMoveLineDTO] = Field(default_factory=list)


class PartnerPricelistDTO(BaseModel):
    """Per-supplier price list entry (purchase_orders module).

    See ``app.modules.purchase_orders.models.PartnerPricelist`` for the
    underlying table. Exposed via ``core_api.purchase_orders.*``.

    Used by:
    - Recipes Tier 0.1 (cost-estimate fallback chain)
    - Procurement UI (compare offers for the same product)
    - Auto-PO generation (pick preferred_partner with lowest price)
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    partner_id: UUID
    product_template_id: UUID
    unit_price: Decimal
    currency: str
    uom_id: UUID | None = None
    min_quantity: Decimal | None = None
    valid_from: date
    valid_to: date | None = None
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PurchaseOrderLineInput(BaseModel):
    """One line of a cross-module Purchase Order creation request.

    Mirrors ``purchase_orders.schemas.PurchaseOrderLineCreate`` without
    leaking module internals to consumers (e.g. shopping_lists).
    """

    product_template_id: UUID | None = None
    name: str | None = Field(default=None, max_length=255)
    quantity_ordered: Decimal = Field(gt=0)
    unit_price: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    uom_id: UUID | None = None
    tax_rate: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    notes: str | None = None


class PurchaseOrderCreateInput(BaseModel):
    """Contract DTO for creating a Purchase Order from another module."""

    partner_id: UUID | None = None
    scheduled_date: date | None = None
    lines: list[PurchaseOrderLineInput] = Field(min_length=1)
    notes: str | None = None
    currency: str | None = Field(default=None, max_length=3)


class PurchaseOrderDTO(BaseModel):
    """Stable cross-module view of a Purchase Order."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    number: str
    status: str
    partner_id: UUID | None = None
    scheduled_date: date | None = None
    currency: str | None = None
    created_by: UUID


class WorkItemQueryDTO(BaseModel):
    """What To do asks a module for: the work due by ``date_to``, soonest first."""

    date_to: date
    limit: int
    user_id: UUID
    #: Set when the reader also wants the work finished since then: a provider
    #: adds its sources completed at or after this moment as ``done`` tasks.
    done_since: datetime | None = None


class WorkItemDTO(BaseModel):
    """One task a module contributes to To do.

    Built-in kinds (a delivery to receive, a production run to make, a count
    due) fill the structured fields and let the screen word the sentence in
    the reader's language. A module the screen has no wording for supplies
    its own ``sentence`` and, for the one thing to do next, ``action_label``
    and ``action_href`` (an in-app path). ``source_kind`` and ``source_id``
    name the record the task is derived from: they key the task's assignee,
    so they must be stable for as long as the task stands.

    ``state`` is read from the module's own records on every request — an
    open session is ``in_progress``, a source finished since
    ``WorkItemQueryDTO.done_since`` is ``done`` (returned only when that is
    asked for), a cancelled source is no longer returned — which is what
    keeps To do free of status changes made by hand.
    """

    kind: str
    source_kind: str
    source_id: UUID
    state: Literal['todo', 'in_progress', 'done'] = 'todo'
    due_date: date | None = None
    number: str | None = None
    subject: str | None = None
    count: Decimal | None = None
    #: The unit ``count`` is in, where it is a quantity of goods.
    unit: str | None = None
    place: str | None = None
    #: A built-in verb (``receive_delivery``, ``produce``, ``count``).
    next_action: str | None = None
    sentence: str | None = None
    action_label: str | None = None
    action_href: str | None = None
    #: When a ``done`` task was finished, where the module records it.
    done_at: datetime | None = None


class DocumentLineToPostDTO(BaseModel):
    """One line of a document a pre-post check is asked about.

    ``expected_quantity`` is what the document planned; ``done_quantity`` is
    what is being posted, filled in by the time the stage is ``post``.
    """

    id: UUID
    line_number: int
    item_id: UUID | None = None
    product_template_id: UUID | None = None
    name: str | None = None
    expected_quantity: Decimal
    done_quantity: Decimal
    uom_id: UUID | None = None
    batch_number: str | None = None
    serial_number: str | None = None
    expiry_date: date | None = None
    source_location_id: UUID | None = None
    target_location_id: UUID | None = None
    #: The order line this line receives against, when it names one: the
    #: column ``source_po_line_id`` on the document line, which stays a
    #: permanent column of the warehouse (see CONTRACTS_STABILITY.md).
    source_po_line_id: UUID | None = None
    #: Modules' own fields on the line, each under its module's name.
    meta_data: dict[str, dict[str, Any]] = Field(default_factory=dict)


class DocumentStateDTO(BaseModel):
    """Where a document stands, for a module that may hold it.

    ``held_by`` names the module a document in ``PENDING_APPROVAL`` waits
    for; empty on every document nothing holds. ``confirmed_by`` is who
    submitted it, once it is confirmed.
    """

    id: UUID
    number: str
    type: str
    status: str
    confirmed_by: UUID | None = None
    held_by: str | None = None


class DocumentToPostDTO(BaseModel):
    """The document a module's pre-post check is asked about.

    ``stage`` is ``confirm`` once a draft has drawn its number and before
    its stock is reserved (a refusal takes the number back), and ``post`` before its stock moves; the one-step action asks
    both, in the same transaction.

    ``confirmed_by`` is who submits the document: the person confirming it
    at ``confirm``, the one who confirmed it at ``post``.
    """

    stage: Literal['confirm', 'post']
    id: UUID
    #: IN, INTERNAL_IN, OUT, INTERNAL_OUT, INT, SCRAP or CORRECTION. OUT,
    #: INTERNAL_OUT, INT and SCRAP take goods off a shelf. The list, with the
    #: line fields, is in docs/subsystems/CROSS_MODULE_EXTENSION.md, Pattern 6.
    type: str
    number: str
    partner_id: UUID | None = None
    source_location_id: UUID | None = None
    target_location_id: UUID | None = None
    scheduled_date: date | None = None
    external_reference: str | None = None
    #: Modules' own fields on the document, each under its module's name: a
    #: check reads its own key to see whether a field it requires was filled.
    meta_data: dict[str, dict[str, Any]] = Field(default_factory=dict)
    confirmed_by: UUID | None = None
    #: Whether the person carrying the posting out holds
    #: ``warehouse:receive_over_tolerance``: a check that weighs a received
    #: quantity against a ceiling lets the surplus past the tolerance through
    #: for them.
    may_exceed_over_receipt: bool = False
    lines: list[DocumentLineToPostDTO] = Field(default_factory=list)


class PickOrderLocationDTO(BaseModel):
    """One step of the walk to a shelf: a location on the way in.

    ``location_path`` is these, outermost first, ending in the shelf itself —
    the zone before the aisle, the aisle before the shelf — so a strategy can
    group by any level of the walk without asking the database again.
    """

    id: UUID
    sequence: int | None = Field(
        None, description='Ordering number among locations, lowest first'
    )
    short_code: str | None = None
    name: str | None = None


class PickOrderLineDTO(BaseModel):
    """One line of a picking session, for a pick-order strategy to sort.

    A strategy registered through ``warehouse_api.register_pick_order_strategy``
    receives these — the lines with their product, quantity, location and
    path — and returns the same lines in the order the picker walks to them.
    """

    id: UUID
    product_template_id: UUID | None = None
    product_name: str | None = None
    quantity: Decimal
    #: The batch the line plans from, named as the picker reads it — what a
    #: strategy keyed on batches (a certificate, an expiry) asks its own
    #: tables about.
    lot_name: str | None = None
    location_id: UUID | None = None
    location_path: list[PickOrderLocationDTO] = Field(default_factory=list)
    #: The shelf as the floor reads it (its caption and the product's code),
    #: which is what two lines on one shelf are told apart by.
    bin_location: str | None = None


class DocumentFilterDTO(BaseModel):
    """What a module's filter narrows the documents list to.

    A provider registered through ``warehouse_api.register_document_filter``
    answers this when a reader turns the filter on. A document stays on the
    list when one of its lines carries, under the module's own name in its
    ``meta_data``, every field of one of ``line_meta_data`` — so ``[{}]``
    keeps the documents with any line the module wrote to, ``[{'number':
    'C-1'}, {'number': 'C-2'}]`` those with either number, and ``[]`` none.
    The warehouse puts the module's name around each fragment itself, so a
    filter reads its own module's fields and no other's.

    ``lots_only`` counts only the lines that carry a batch (a non-empty
    ``batch_number``): a filter answering for a rule about lots — "the
    receipts whose lots are certified" — would otherwise keep a document
    for a field written on one of its lines that is no lot at all.
    """

    line_meta_data: list[dict[str, Any]] = Field(default_factory=list)
    lots_only: bool = False


class PutawayCandidateDTO(BaseModel):
    """One receipt line the putaway ranking is placing, and the shelves offered.

    A criterion registered through ``warehouse_api.register_putaway_criterion``
    receives this for every line a putaway rule takes: the product, its
    category, the quantity in the product's stock unit, and the rule's shelves
    in the order the ranking walks them. It answers which of those shelves may
    not take this line; the ranking walks the rest.
    """

    product_template_id: UUID | None = None
    category_id: UUID | None = None
    quantity: Decimal | None = None
    location_ids: list[UUID] = Field(default_factory=list)


class CountDifferenceDTO(BaseModel):
    """One difference a count found, for the document that records it.

    ``quantity_delta`` is signed — what the counter saw minus what the record
    held — in the unit ``uom_id`` names (the record's own when empty).
    ``location_id`` is where the corrected stock stands, which in a count of
    a rack is one of its shelves (the document's location when empty).
    """

    item_id: UUID
    location_id: UUID | None = None
    product_template_id: UUID | None = None
    name: str
    quantity_delta: Decimal
    uom_id: UUID | None = None
    batch_number: str | None = None
    notes: str | None = None


class LabelScanDTO(BaseModel):
    """What a scan provider answers the label-scan endpoint.

    A provider in a module builds this shape, and the API's response model is
    the same fields under its published name (``app.schemas.label_pool
    .LabelScanResponse``). The line under the status is a catalogue key and
    the values it needs, not a sentence: the reader's client resolves it in
    the reader's language, because a server cannot know it.
    """

    status: str  # 'unassigned' | 'assigned' | 'storage_context' | 'archived' | 'product_stock' | 'document'
    label_code: str
    message_key: str | None = None
    message_params: dict[str, str] | None = None
    action: str  # 'show_quick_add' | 'show_quick_actions' | 'set_storage_context' | 'show_archived_info' | 'show_stock_actions' | 'open_document'
    item: dict[str, Any] | None = None
    location: dict[str, Any] | None = None
    stock_summary: dict[str, Any] | None = None
    quick_actions: list[str] | None = None
    context_tag: str | None = None
    # A scanned document printout: the payload the frontend needs to open the
    # document, and how to open it — continuation for a DRAFT, preview for
    # anything finished.
    document: dict[str, Any] | None = None
    document_mode: str | None = None  # 'continue' | 'preview'
