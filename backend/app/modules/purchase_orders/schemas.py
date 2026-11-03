"""Purchase Order Pydantic schemas."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from sqlalchemy import inspect as sa_inspect

from app.core.exceptions import ServiceRejectionError
from app.core.money import line_amounts
from app.schemas.pagination import PaginatedResponse

# ISO 4217 codes accepted by this module's currency fields. Kept as a closed
# set rather than a shape-only check so "DOL" (three letters, no currency)
# cannot be written; mirrored in frontend/src/lib/currencies.ts and pinned
# equal by currencies.test.ts.
CURRENCY_CODES: frozenset[str] = frozenset(
    {
        'AED',
        'AUD',
        'BGN',
        'BRL',
        'CAD',
        'CHF',
        'CNY',
        'CZK',
        'DKK',
        'EUR',
        'GBP',
        'HKD',
        'HUF',
        'ILS',
        'INR',
        'ISK',
        'JPY',
        'KRW',
        'MXN',
        'NOK',
        'NZD',
        'PLN',
        'RON',
        'SEK',
        'SGD',
        'TRY',
        'UAH',
        'USD',
        'ZAR',
    }
)


class _CurrencyValidationMixin(BaseModel):
    """Normalise and validate the ``currency`` field shared by the write schemas.

       The field used to be a bare three-letter string, so ``"dolary"`` became
    ``"DOL"`` and was accepted as a currency code. The mixin rejects
       any code outside the curated ISO 4217 set; inheriting schemas declare the
       field themselves.
    """

    @field_validator('currency', mode='before', check_fields=False)
    @classmethod
    def _validate_currency(cls, value: object) -> str | None:
        if value is None or value == '':
            return None
        code = str(value).strip().upper()
        if code not in CURRENCY_CODES:
            raise ServiceRejectionError('invalid_currency_code')
        return code


class PurchaseOrderLineCreate(BaseModel):
    """Line item for PO creation."""

    product_template_id: UUID | None = None
    name: str | None = Field(default=None, max_length=255)
    quantity_ordered: Decimal = Field(gt=0)
    unit_price: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    uom_id: UUID | None = None
    tax_rate: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    notes: str | None = None
    # Provenance: the reorder rule whose alert this line replenishes.
    # Set by the draft-from-alerts flow; None on a hand-written order.
    source_reorder_rule_id: UUID | None = None

    @model_validator(mode='after')
    def validate_item_or_name(self) -> Self:
        if not self.product_template_id and not self.name:
            raise ValueError('Provide product_template_id or name')
        return self


class PurchaseOrderLineSchema(BaseModel):
    """PO line in response."""

    id: UUID
    purchase_order_id: UUID
    product_template_id: UUID | None
    name: str
    quantity_ordered: Decimal
    quantity_received: Decimal
    unit_price: Decimal | None
    uom_id: UUID | None
    uom_symbol: str | None = None
    tax_rate: Decimal | None
    line_number: int
    notes: str | None
    source_reorder_rule_id: UUID | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode='before')
    @classmethod
    def _populate_uom_symbol(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return data
        uom = getattr(data, 'uom', None)
        # The template relationship is selectin-loaded on every read path,
        # but a freshly created order may still carry it unloaded -- reading
        # it there would start a lazy load the async session refuses. The
        # name fallback resolves only what is already in memory; the create
        # service re-reads the order so this finds the template on the
        # response that created it too.
        state = sa_inspect(data)
        template = (
            data.product_template if 'product_template' not in state.unloaded else None
        )
        # The UI always sends a name; the API path (a line created from a
        # product template with no name) stored an empty one, and the reader
        # met a row that named nothing. The template is one relationship
        # away, so the response answers with its name while the stored
        # column keeps what was written.
        name = data.name or (template.name if template is not None else '')
        return {
            'id': data.id,
            'purchase_order_id': data.purchase_order_id,
            'product_template_id': data.product_template_id,
            'name': name,
            'quantity_ordered': data.quantity_ordered,
            'quantity_received': data.quantity_received,
            'unit_price': data.unit_price,
            'uom_id': data.uom_id,
            'uom_symbol': uom.symbol if uom is not None else None,
            'tax_rate': data.tax_rate,
            'line_number': data.line_number,
            'notes': data.notes,
            'source_reorder_rule_id': data.source_reorder_rule_id,
        }


class PurchaseOrderCreate(_CurrencyValidationMixin):
    """Request body for PO creation."""

    partner_id: UUID | None = None
    scheduled_date: date | None = None
    lines: list[PurchaseOrderLineCreate] = Field(min_length=1)
    notes: str | None = None
    currency: str | None = Field(default=None, max_length=3)


class PurchaseOrderUpdate(_CurrencyValidationMixin):
    """Request body for PO update."""

    partner_id: UUID | None = None
    scheduled_date: date | None = None
    notes: str | None = None
    # An order with no lines is not an order. Omitting ``lines`` leaves them
    # untouched; sending an empty list used to empty a draft that could then
    # be confirmed and e-mailed to a supplier.
    lines: list[PurchaseOrderLineCreate] | None = Field(default=None, min_length=1)
    currency: str | None = Field(default=None, max_length=3)


class PurchaseOrderSchema(BaseModel):
    """Full PO response."""

    id: UUID
    organization_id: UUID
    number: str
    status: Literal['DRAFT', 'PENDING_APPROVAL', 'CONFIRMED', 'CANCELLED', 'COMPLETED']
    partner_id: UUID | None
    partner_name: str | None = None
    scheduled_date: date | None
    notes: str | None
    currency: str | None = None
    created_by: UUID
    confirmed_by: UUID | None
    confirmed_at: datetime | None
    cancelled_by: UUID | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lines: list[PurchaseOrderLineSchema]
    total_net: Decimal | None = None
    total_tax: Decimal | None = None
    total_gross: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode='before')
    @classmethod
    def _attach_partner_and_totals(cls, data: Any) -> Any:
        """Attach partner name and line totals for list/detail rows.

        ``PurchaseOrder.partner`` and ``.lines`` are loaded eagerly
        (``lazy='selectin'``), so this runs without extra queries.

        A line with no price leaves all three totals ``None``: the order's
        worth cannot be stated, which is what the approval rule says too
        (``po_net_total``). Summing what could be summed printed 0.00 for an
        order of unpriced lines, and a partial sum for the rest.
        """
        if isinstance(data, dict):
            return data
        partner = getattr(data, 'partner', None)
        partner_name = None
        if partner is not None:
            partner_name = getattr(partner, 'name', None)
        lines = getattr(data, 'lines', None) or []
        total_net = Decimal('0')
        total_tax = Decimal('0')
        every_line_priced = True
        for line in lines:
            price = getattr(line, 'unit_price', None)
            qty = getattr(line, 'quantity_ordered', None)
            if price is None or qty is None:
                every_line_priced = False
                continue
            amounts = line_amounts(
                qty, price, getattr(line, 'tax_rate', None), places=None
            )
            total_net += amounts.net
            total_tax += amounts.tax
        return {
            'id': data.id,
            'organization_id': data.organization_id,
            'number': data.number,
            'status': data.status,
            'partner_id': data.partner_id,
            'partner_name': partner_name,
            'scheduled_date': data.scheduled_date,
            'notes': data.notes,
            'currency': data.currency,
            'created_by': data.created_by,
            'confirmed_by': data.confirmed_by,
            'confirmed_at': data.confirmed_at,
            'cancelled_by': data.cancelled_by,
            'cancelled_at': data.cancelled_at,
            'created_at': data.created_at,
            'updated_at': data.updated_at,
            'lines': [PurchaseOrderLineSchema.model_validate(line) for line in lines],
            'total_net': total_net if every_line_priced else None,
            'total_tax': total_tax if every_line_priced else None,
            'total_gross': total_net + total_tax if every_line_priced else None,
        }


class PurchaseOrderTargetSummaryDTO(BaseModel):
    """What an approver needs to see about a purchase order.

    The approvals queue rendered eight characters of a UUID for every request
    that was not a document — on the one screen whose whole job is deciding
    about a spend. ``total_value`` is the net total, the same figure the
    approval threshold is compared against, so the card and the rule that
    raised it speak about the same number.
    """

    id: UUID
    number: str
    partner_name: str | None = None
    total_value: Decimal | None = None
    currency: str | None = None
    lines_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class PurchaseOrderUnitProgressSchema(BaseModel):
    """What an order's lines in one unit ordered and received, summed.

    Kept per unit: 20 pcs and 12.5 kg are not 32.5 of anything.
    """

    unit: str | None
    ordered: Decimal
    received: Decimal


@dataclass
class OrderLineTally:
    """What the list prints of an order's lines, summed in the database.

    ``net`` and ``tax_basis`` are the priced lines' ``quantity × price`` and
    ``quantity × price × rate``; the tax is the basis over a hundred, which
    is exactly what ``line_amounts`` adds up line by line — the same digits
    the card prints. ``unpriced`` counts the lines with no price: one of them
    leaves the order without a total, as it does on the card.
    """

    count: int = 0
    unit_progress: list[PurchaseOrderUnitProgressSchema] = field(default_factory=list)
    net: Decimal | None = None
    tax_basis: Decimal | None = None
    unpriced: int = 0


class PurchaseOrderListRowSchema(PurchaseOrderSchema):
    """An order as the list shows it: its lines counted and summed.

    ``lines`` is empty unless the list was asked ``with_lines`` — the receive
    screen, choosing which open order's lines to receive. The list itself
    prints a count, the receipt progress per unit and the totals, summed in
    the database: carried whole, the lines made a page of fifty orders
    400 KB, and built only to be dropped, they stalled a page every few
    requests.
    """

    line_count: int
    unit_progress: list[PurchaseOrderUnitProgressSchema]

    @classmethod
    def of(cls, order: PurchaseOrderSchema, tally: OrderLineTally) -> Self:
        net = tally.net if tally.net is not None else Decimal('0')
        tax = (
            tally.tax_basis / Decimal('100')
            if tally.tax_basis is not None
            else Decimal('0')
        )
        known = not tally.unpriced
        return cls(
            **order.model_dump(exclude={'total_net', 'total_tax', 'total_gross'}),
            line_count=tally.count,
            unit_progress=tally.unit_progress,
            total_net=net if known else None,
            total_tax=tax if known else None,
            total_gross=net + tax if known else None,
        )


class PurchaseOrderApprovalRequirement(BaseModel):
    """What confirming this order would do, for the person asking.

    ``approval_required`` says whether confirming goes to approval.
    ``approval_solvable`` is ``False`` where a request raised now, by confirming
    or by asking for approval directly, would wait at a stage nobody could
    decide for them, whether or not the rules require one; the two fields after
    it say why, in the approvals module's stable codes, and which stage.
    """

    approval_required: bool
    approval_solvable: bool = True
    undecidable_reason: str | None = None
    undecidable_stage: str | None = None


class PurchaseOrderListResponse(PaginatedResponse[PurchaseOrderListRowSchema]):
    """Paginated PO list response."""


class ReceiptLineInput(BaseModel):
    """Single line input for partial receipt."""

    po_line_id: UUID
    quantity: Decimal = Field(gt=0)
    #: For an order line typed by hand: the product its goods arrive as, named
    #: by whoever receives them. It stays on the order line. A line that
    #: already names a product keeps its own.
    product_template_id: UUID | None = None


class CreateReceiptFromPO(BaseModel):
    """Request body for creating PZ from PO."""

    target_location_id: UUID
    lines: list[ReceiptLineInput] | None = None


class LinkedReceiptSchema(BaseModel):
    """Minimal document summary for linked receipts."""

    id: UUID
    number: str
    type: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReceiptLineSchema(BaseModel):
    """Document line returned within a receipt created from PO."""

    id: UUID
    document_id: UUID
    product_template_id: UUID | None = None
    name: str | None = None
    quantity: Decimal
    expected_quantity: Decimal
    done_quantity: Decimal
    uom_id: UUID | None = None
    source_po_line_id: UUID | None = None
    unit_price: Decimal | None = None
    tax_rate: Decimal | None = None
    line_number: int
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ReceiptFromPOSchema(BaseModel):
    """Document created from a Purchase Order.

    PO-local response schema — avoids importing ``DocumentSchema``
    from the warehouse module.
    """

    id: UUID
    organization_id: UUID
    type: str
    number: str
    status: str
    partner_id: UUID | None = None
    target_location_id: UUID | None = None
    scheduled_date: date | None = None
    notes: str | None = None
    external_reference: str | None = None
    lines: list[ReceiptLineSchema] = []
    created_by: UUID
    confirmed_by: UUID | None = None
    completed_by: UUID | None = None
    created_at: datetime
    confirmed_at: datetime | None = None
    completed_at: datetime | None = None
    total_net: Decimal | None = None
    total_tax: Decimal | None = None
    total_gross: Decimal | None = None
    # The totals above are the order's amounts, so the sign in front of them
    # has to be the order's too — a receipt inherits the currency it was
    # priced in rather than the organization's.
    currency: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PartnerPricelistCreate(_CurrencyValidationMixin):
    """Create a new supplier price list entry."""

    partner_id: UUID
    product_template_id: UUID
    unit_price: Decimal = Field(gt=0, max_digits=12, decimal_places=4)
    # no default currency here. A price list that quietly recorded USD
    # for an organization trading in PLN put dollar prices onto order lines,
    # which is how a list of orders ended up mixing $30.00 with PLN 30.00.
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    uom_id: UUID | None = None
    min_quantity: Decimal | None = Field(
        default=None, gt=0, max_digits=12, decimal_places=3
    )
    valid_from: date
    valid_to: date | None = None
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PartnerPricelistUpdate(_CurrencyValidationMixin):
    """Patch an existing supplier price list entry."""

    unit_price: Decimal | None = Field(
        default=None, gt=0, max_digits=12, decimal_places=4
    )
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    uom_id: UUID | None = None
    min_quantity: Decimal | None = Field(
        default=None, gt=0, max_digits=12, decimal_places=3
    )
    valid_from: date | None = None
    valid_to: date | None = None
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PartnerPricelistSchema(BaseModel):
    """Response schema for a supplier price list entry."""

    id: UUID
    organization_id: UUID
    partner_id: UUID
    product_template_id: UUID
    product_name: str = ''
    unit_price: Decimal
    currency: str
    uom_id: UUID | None = None
    min_quantity: Decimal | None = None
    valid_from: date
    valid_to: date | None = None
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ReorderRuleCreate(BaseModel):
    """Create a reorder rule for one (product, location) pair.

    ``min_quantity`` is the threshold that makes the rule fire; ``max_quantity``
    is only the level to reach once it has. Requiredness used to be the other
    way round -- MIN defaulted to 0 -- and the engine skips a rule at 0
    outright, so a rule saved with the required fields alone could never
    produce an alert while sitting on the list looking like every other one.
    """

    product_template_id: UUID
    location_id: UUID
    min_quantity: Decimal = Field(gt=0)
    max_quantity: Decimal = Field(gt=0)
    safety_stock: Decimal = Field(default=Decimal('0'), ge=0)
    preferred_partner_id: UUID | None = None
    notes: str | None = None


class ReorderRuleUpdate(BaseModel):
    """Patch an existing reorder rule.

    None means "leave it alone"; a value has to be one the engine can act on,
    so a rule cannot be edited down into the state it cannot be created in.
    """

    min_quantity: Decimal | None = Field(default=None, gt=0)
    max_quantity: Decimal | None = None
    safety_stock: Decimal | None = None
    preferred_partner_id: UUID | None = None
    notes: str | None = None


class ReorderRuleSchema(BaseModel):
    """Response schema for a reorder rule."""

    id: UUID
    organization_id: UUID
    product_template_id: UUID
    product_name: str = ''
    # Resolved from the product template so the edit form can show the unit
    # next to the thresholds; None when the product has no unit.
    uom_id: UUID | None = None
    uom_symbol: str | None = None
    location_id: UUID
    min_quantity: Decimal
    max_quantity: Decimal
    safety_stock: Decimal
    preferred_partner_id: UUID | None = None
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # The shelf's side of the same (product, location) pair, resolved by the
    # router at response time. None = no capacity set — not zero: a shelf
    # with no entry has no limit, and the form must not read that as an
    # overflow. ``over_capacity`` says the rule wants more than the shelf
    # holds — a warning, not a refusal.
    capacity_max_quantity: Decimal | None = None
    over_capacity: bool = False

    model_config = ConfigDict(from_attributes=True)


class POSettingsSchema(BaseModel):
    """Response schema for per-org PO approval settings."""

    id: UUID
    organization_id: UUID
    approval_threshold: Decimal | None = None
    approval_required: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class POSettingsUpdate(BaseModel):
    """Update payload for PO approval settings."""

    approval_threshold: Decimal | None = Field(default=None, ge=0)
    approval_required: bool | None = None


class ReplenishmentDraftPosCreate(BaseModel):
    """Request body for draft-PO creation from replenishment alerts.

    The reorder rules whose current alerts should become draft purchase
    orders — one DRAFT PO per distinct preferred supplier among them.
    """

    reorder_rule_ids: list[UUID] = Field(min_length=1)


class ReplenishmentDraftSkipped(BaseModel):
    """A requested rule that did not become a PO line, with the reason.

    ``reason`` is a stable machine code the UI translates:
    ``not_found`` (no such rule in this org), ``not_alerting`` (stock is
    at or above the minimum right now), ``covered_by_reserve`` (the
    proposed internal move covers the whole shortage, so there is nothing
    to buy), ``no_supplier`` (neither the rule nor the price list names
    a supplier —
    reported, never turned into an empty order).
    """

    reorder_rule_id: UUID
    product_name: str = ''
    reason: str


class ReplenishmentDraftPosResult(BaseModel):
    """Result of the draft-from-alerts action: the orders created and
    the requested rules left out, each with its reason."""

    created: list[PurchaseOrderSchema]
    skipped: list[ReplenishmentDraftSkipped]
