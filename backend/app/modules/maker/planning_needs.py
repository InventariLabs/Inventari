"""What the planned runs of a period need, what is on hand and on order, and ordering the rest.

The planner's question is not "can this run be made" (``planning_service`` and
completion answer that) but "what do I have to get for next week". This reads
the draft runs of a period — or one run — as one list of needs: per ingredient
what is needed, what the shelf holds once the runs planned before the period
have taken their share, what open purchase orders still expect (with their
dates) and what is still missing.

The list stops at the first level of each formula. An ingredient that has a
recipe of its own is something to *make*: its missing part is proposed as a
planned run of that product, never as a purchase, and its raw materials belong
to that run once it is planned.

Purchasing is another module. With it off the answer carries no on-order
figure at all (``on_order`` is ``None``, not zero), and ordering is refused —
the shelf and the shopping list still work.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    OpenOrderLineDTO,
    PartnerPricelistDTO,
    ProductTemplateDTO,
    PurchaseOrderCreateInput,
    PurchaseOrderLineInput,
    UomDTO,
    UserContextDTO,
)
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api
from app.i18n import Language

from . import bom_service, planning_service, recipe_service
from .availability_service import _get_available_stock_batch, _resolve_scope
from .models import ProductionOrder

NeedAction = Literal['buy', 'make']


@dataclass(frozen=True)
class ExpectedDelivery:
    """An open purchase order line that will bring some of an ingredient."""

    purchase_order_id: UUID
    number: str
    expected_date: date | None
    quantity: Decimal


@dataclass
class NeedRow:
    """One ingredient of the combined list, all quantities in its stock unit."""

    template_id: UUID
    name: str | None
    uom_symbol: str | None
    needed: Decimal
    in_stock: Decimal
    #: ``None`` while purchasing is off: the column does not exist then.
    on_order: Decimal | None
    expected: list[ExpectedDelivery]
    missing: Decimal
    #: What draft runs of the ingredient itself already bring, once the runs
    #: before the period have taken their share: a sub-assembly that is
    #: planned is not missing.
    planned: Decimal
    #: ``make`` for an ingredient that has a recipe of its own.
    action: NeedAction
    #: The first planned day, and the output shelf, of the runs that need it.
    needed_by: date | None = None
    output_location_id: UUID | None = None


@dataclass
class NeedsView:
    rows: list[NeedRow] = field(default_factory=list)
    purchasing: bool = False
    run_count: int = 0
    #: Ingredients whose measure cannot be compared with their stock unit:
    #: they are left out of the figures and named here instead.
    unmeasured: list[str] = field(default_factory=list)


async def purchasing_enabled(db: AsyncSession, organization_id: UUID) -> bool:
    return await core_api.organizations.is_module_enabled_async(
        db, organization_id, 'purchase_orders'
    )


async def _open_orders(
    db: AsyncSession, organization_id: UUID, template_ids: list[UUID]
) -> list[OpenOrderLineDTO]:
    from app.modules.purchase_orders.purchase_orders_api import purchase_orders_api

    return await purchase_orders_api.list_open_order_lines_async(
        db, organization_id, template_ids
    )


def _to_stock_unit(
    qty: Decimal,
    line_uom_id: UUID | None,
    stock_uom_id: UUID | None,
    uoms: dict[UUID, UomDTO],
) -> Decimal | None:
    """*qty* in the ingredient's stock unit; ``None`` when no bridge exists."""
    if line_uom_id is None or stock_uom_id is None or line_uom_id == stock_uom_id:
        return qty
    source, target = uoms.get(line_uom_id), uoms.get(stock_uom_id)
    if source is None or target is None:
        return qty
    converted, ok = core_api.uoms.convert_quantity(qty, source, target)
    return converted if ok else None


def _need_row(
    tid: UUID,
    template: ProductTemplateDTO | None,
    uoms: dict[UUID, UomDTO],
    *,
    needed: Decimal,
    in_stock: Decimal,
    deliveries: list[ExpectedDelivery],
    purchasing: bool,
    freshly_made: Decimal,
    planned: Decimal,
    makes: bool,
    first_run: ProductionOrder,
) -> NeedRow:
    """One ingredient's row: what is covered by the shelf and by what is on its way.

    A line that never takes the sub-assembly from the shelf needs it made
    whatever is in stock (*freshly_made*); the rest of the need is covered by
    the stock first and by the open orders after it. Runs already planned of
    the ingredient itself (*planned*) cover what is still missing after that.
    """
    on_order = (
        sum((d.quantity for d in deliveries), Decimal('0')) if purchasing else None
    )
    covered_by = in_stock + (on_order or Decimal('0'))
    missing = max(
        Decimal('0'),
        max(Decimal('0'), needed - freshly_made - covered_by) + freshly_made - planned,
    )
    uom = uoms.get(template.uom_id) if template and template.uom_id else None
    return NeedRow(
        template_id=tid,
        name=template.name if template else None,
        uom_symbol=uom.symbol if uom else None,
        needed=needed,
        in_stock=in_stock,
        on_order=on_order,
        expected=deliveries,
        missing=missing,
        planned=planned,
        action='make' if makes else 'buy',
        needed_by=first_run.production_date,
        output_location_id=first_run.output_storage_location_id,
    )


@dataclass
class _Tally:
    """What the queue asks of each ingredient, and the shelf the period opens on."""

    needed: dict[UUID, Decimal] = field(default_factory=dict)
    fresh: dict[UUID, Decimal] = field(default_factory=dict)
    has_recipe: set[UUID] = field(default_factory=set)
    scopes_used: dict[UUID, set[UUID | None]] = field(default_factory=dict)
    first_run: dict[UUID, ProductionOrder] = field(default_factory=dict)
    unmeasured: set[UUID] = field(default_factory=set)
    #: What the runs before the period asked for beyond the shelf: it was
    #: spoken for by whatever is on its way, so the period cannot count it.
    overflow: dict[UUID, Decimal] = field(default_factory=dict)
    #: Per ingredient, what each run of the period asks for and on which day.
    asked: dict[UUID, list[tuple[tuple[bool, date], Decimal]]] = field(
        default_factory=dict
    )
    start_left: dict[UUID | None, dict[UUID, Decimal]] | None = None


def _claim_in_queue(
    queue: list[ProductionOrder],
    scopes: list[UUID | None],
    run_needs: list[list[bom_service.DirectNeed]],
    left: dict[UUID | None, dict[UUID, Decimal]],
    templates: dict[UUID, ProductTemplateDTO],
    uoms: dict[UUID, UomDTO],
    selected: Callable[[ProductionOrder], bool],
) -> _Tally:
    """Walk the queue: every run claims its needs off the shelf, in order.

    The runs of the period add to the tally; the runs before it only spend
    the shelf, and the shelf is copied the moment the first run of the period
    is reached — that copy is what the period starts with.
    """
    tally = _Tally()
    for order, scope, needs in zip(queue, scopes, run_needs, strict=True):
        in_period = selected(order)
        if in_period and tally.start_left is None:
            tally.start_left = {sc: dict(stock) for sc, stock in left.items()}
        for need in needs:
            tid = need.child_template_id
            template = templates.get(tid)
            claimed = _to_stock_unit(
                need.qty, need.uom_id, template.uom_id if template else None, uoms
            )
            if claimed is None:
                if in_period:
                    tally.unmeasured.add(tid)
                continue
            if in_period:
                tally.needed[tid] = tally.needed.get(tid, Decimal('0')) + claimed
                tally.scopes_used.setdefault(tid, set()).add(scope)
                tally.asked.setdefault(tid, []).append(
                    (planning_service.planned_day(order), claimed)
                )
                tally.first_run.setdefault(tid, order)
                if need.has_recipe:
                    tally.has_recipe.add(tid)
                    if need.make_fresh:
                        tally.fresh[tid] = tally.fresh.get(tid, Decimal('0')) + claimed
            stock = left[scope]
            on_hand = stock.get(tid, Decimal('0'))
            if not in_period and claimed > on_hand:
                tally.overflow[tid] = tally.overflow.get(tid, Decimal('0')) + (
                    claimed - on_hand
                )
            stock[tid] = max(Decimal('0'), on_hand - claimed)
    return tally


def _planned_supply(
    made: list[tuple[tuple[bool, date], Decimal]],
    asked: list[tuple[tuple[bool, date], Decimal]],
) -> Decimal:
    """How much of what the period asks a planned run makes in time for it.

    A run's output is there for the runs planned on its day or after it, the
    same day included whatever the creation order; a run planned later makes
    nothing for the ones before it.
    """
    events = [(day, 0, qty) for day, qty in made] + [
        (day, 1, qty) for day, qty in asked
    ]
    supply = Decimal('0')
    taken = Decimal('0')
    for _day, kind, qty in sorted(events, key=lambda e: (e[0], e[1])):
        if kind == 0:
            supply += qty
        else:
            used = min(qty, supply)
            supply -= used
            taken += used
    return taken


def _after_earlier_claims(
    deliveries: list[ExpectedDelivery], claimed: Decimal
) -> tuple[list[ExpectedDelivery], Decimal]:
    """What the earlier runs left of the deliveries, and what they claimed beyond them.

    The runs before the period ask for more than the shelf had; what is on
    its way goes to them first, the earliest delivery first, as the shelf does.
    """
    left: list[ExpectedDelivery] = []
    for delivery in sorted(
        deliveries, key=lambda d: (d.expected_date is None, d.expected_date or date.min)
    ):
        taken = min(claimed, delivery.quantity)
        claimed -= taken
        if delivery.quantity > taken:
            left.append(
                ExpectedDelivery(
                    delivery.purchase_order_id,
                    delivery.number,
                    delivery.expected_date,
                    delivery.quantity - taken,
                )
            )
    return left, claimed


def ensure_scope(
    date_from: date | None, date_to: date | None, order_id: UUID | None
) -> None:
    """Refuse a request that names neither one run nor a whole period, or both."""
    if date_from is not None and date_to is not None:
        if order_id is not None:
            raise ServiceRejectionError('production_needs_scope')
        if date_from > date_to:
            raise ServiceRejectionError('production_needs_period_reversed')
    elif order_id is None or date_from is not None or date_to is not None:
        raise ServiceRejectionError('production_needs_scope')


def _selector(
    date_from: date | None, date_to: date | None, order_id: UUID | None
) -> Callable[[ProductionOrder], bool]:
    """Which runs a request is about: the one it names, or those planned in the period.

    A run with no planned day is in no period.
    """

    def selected(order: ProductionOrder) -> bool:
        if order_id is not None:
            return order.id == order_id
        day = order.production_date
        return (
            day is not None
            and date_from is not None
            and date_to is not None
            and date_from <= day <= date_to
        )

    return selected


async def needs_for(
    db: AsyncSession,
    organization_id: UUID,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    order_id: UUID | None = None,
) -> NeedsView:
    """The combined needs of the draft runs planned in a period, or of one run.

    A run is in the period when its planned day lies in
    ``date_from..date_to``; runs with no planned day are in no period. The
    runs queued before the first of them take their share of the shelf first
    (the order ``planning_service`` queues them in), so ``in_stock`` is what
    is left for the period, not what the shelf holds today.
    """
    ensure_scope(date_from, date_to, order_id)
    queue = await planning_service.queued_drafts(db, organization_id)

    selected = _selector(date_from, date_to, order_id)
    last = max((i for i, o in enumerate(queue) if selected(o)), default=None)
    view = NeedsView(purchasing=await purchasing_enabled(db, organization_id))
    if last is None:
        return view
    # Runs planned on the day of the last one count as supply for it, though
    # they were created after it and so stand behind it in the queue.
    last_day = planning_service.planned_day(queue[last])
    makers = [o for o in queue if planning_service.planned_day(o) <= last_day]
    queue = queue[: last + 1]
    view.run_count = sum(1 for o in queue if selected(o))

    settings = await recipe_service.get_settings(db, organization_id, for_update=False)

    def scope_of(order_location: UUID | None) -> UUID | None:
        return _resolve_scope(settings.availability_check_scope, None, order_location)

    run_needs = [
        await bom_service.direct_needs(
            db, organization_id, order.recipe_id, order.planned_qty
        )
        for order in queue
        if order.recipe_id is not None
    ]
    scopes = [scope_of(o.output_storage_location_id) for o in queue]

    children_by_scope: dict[UUID | None, set[UUID]] = {}
    for scope, needs in zip(scopes, run_needs, strict=True):
        children_by_scope.setdefault(scope, set()).update(
            n.child_template_id for n in needs
        )
    left: dict[UUID | None, dict[UUID, Decimal]] = {
        scope: await _get_available_stock_batch(
            db, organization_id, sorted(children), location_id=scope
        )
        for scope, children in children_by_scope.items()
    }
    all_children = sorted(set().union(*children_by_scope.values()))
    templates: dict[UUID, ProductTemplateDTO] = (
        await core_api.product_templates.get_many_async(
            db, organization_id, all_children
        )
        if all_children
        else {}
    )
    uoms = {
        u.id: u for u in await core_api.uoms.list_for_org_async(db, organization_id)
    }

    tally = _claim_in_queue(queue, scopes, run_needs, left, templates, uoms, selected)
    needed, fresh = tally.needed, tally.fresh
    has_recipe, scopes_used, first_run = (
        tally.has_recipe,
        tally.scopes_used,
        tally.first_run,
    )
    unmeasured = tally.unmeasured
    start_left = tally.start_left

    opening = start_left or {}
    made: dict[UUID, list[tuple[tuple[bool, date], Decimal]]] = {}
    for order in makers:
        if order.output_template_id in needed:
            made.setdefault(order.output_template_id, []).append(
                (planning_service.planned_day(order), order.planned_qty)
            )
    open_lines: list[OpenOrderLineDTO] = (
        await _open_orders(db, organization_id, sorted(needed))
        if view.purchasing and needed
        else []
    )
    for tid in sorted(
        needed, key=lambda t: templates[t].name if t in templates else ''
    ):
        template = templates.get(tid)
        in_stock = sum(
            (
                opening.get(scope, {}).get(tid, Decimal('0'))
                for scope in scopes_used[tid]
            ),
            Decimal('0'),
        )
        deliveries, unmet = _after_earlier_claims(
            [
                ExpectedDelivery(
                    purchase_order_id=line.purchase_order_id,
                    number=line.number,
                    expected_date=line.expected_date,
                    quantity=line.outstanding_quantity,
                )
                for line in open_lines
                if line.product_template_id == tid
            ],
            tally.overflow.get(tid, Decimal('0')),
        )
        view.rows.append(
            _need_row(
                tid,
                template,
                uoms,
                needed=needed[tid],
                in_stock=in_stock,
                deliveries=deliveries,
                purchasing=view.purchasing,
                freshly_made=fresh.get(tid, Decimal('0')),
                planned=max(
                    Decimal('0'),
                    _planned_supply(made.get(tid, []), tally.asked.get(tid, []))
                    - unmet,
                ),
                makes=tid in has_recipe,
                first_run=first_run[tid],
            )
        )
    view.unmeasured = sorted(templates[t].name for t in unmeasured if t in templates)
    return view


# ---------------------------------------------------------------------------
# Ordering what is missing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Offer:
    partner_id: UUID
    unit_price: Decimal
    currency: str
    uom_id: UUID | None
    quantity: Decimal  # what to order, in the offer's unit
    per_stock_unit: Decimal  # price per one stock unit, to compare offers


def _best_offer(
    missing: Decimal,
    template: ProductTemplateDTO,
    prices: list[PartnerPricelistDTO],
    uoms: dict[UUID, UomDTO],
) -> _Offer | None:
    """The cheapest supplier price, compared per stock unit, stated in its own unit.

    A supplier sells in its own unit (a 25 kg sack), and the quantity to order
    is the missing quantity expressed in it, put up to a whole step of that
    unit and to the supplier's minimum. An offer in a unit that has no bridge
    to the product's stock unit cannot be compared or ordered and is passed
    over.
    """
    stock_uom = uoms.get(template.uom_id) if template.uom_id else None
    best: _Offer | None = None
    for entry in prices:
        offer_uom = uoms.get(entry.uom_id) if entry.uom_id else None
        if offer_uom is None or stock_uom is None or offer_uom.id == stock_uom.id:
            quantity, per_stock, unit_uom = missing, entry.unit_price, entry.uom_id
        else:
            converted, ok = core_api.uoms.convert_quantity(
                missing, stock_uom, offer_uom
            )
            one, one_ok = core_api.uoms.convert_quantity(
                Decimal('1'), offer_uom, stock_uom
            )
            if not ok or not one_ok or one <= 0:
                continue
            quantity, per_stock, unit_uom = (
                converted,
                entry.unit_price / one,
                entry.uom_id,
            )
        quantity = core_api.uoms.round_up(quantity, offer_uom or stock_uom)
        if entry.min_quantity is not None:
            quantity = max(quantity, entry.min_quantity)
        offer = _Offer(
            entry.partner_id,
            entry.unit_price,
            entry.currency,
            unit_uom,
            quantity,
            per_stock,
        )
        if best is None or offer.per_stock_unit < best.per_stock_unit:
            best = offer
    return best


@dataclass
class OrderedLine:
    template_id: UUID
    name: str | None
    quantity: Decimal
    uom_symbol: str | None


@dataclass
class OrderedPurchase:
    purchase_order_id: UUID
    number: str
    partner_id: UUID
    lines: list[OrderedLine]


@dataclass
class OrderMissingResult:
    purchase_orders: list[OrderedPurchase] = field(default_factory=list)
    #: Ingredients no supplier offers: sent to the shopping list, as before.
    shopping_list_added: int = 0
    shopping_list_name: str | None = None
    #: Ingredients with no supplier that could not go to a list either.
    unplaced: list[NeedRow] = field(default_factory=list)
    #: Missing ingredients that have a recipe of their own: to be made.
    to_make: list[NeedRow] = field(default_factory=list)


async def order_missing(
    db: AsyncSession,
    organization_id: UUID,
    user: UserContextDTO,
    lang: Language,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    order_id: UUID | None = None,
) -> OrderMissingResult:
    """Order what the combined list says is missing: one draft order per supplier.

    Each missing ingredient goes to the supplier whose price is lowest per
    stock unit, in that supplier's unit. An ingredient nobody offers goes to
    the shopping list. One that has a recipe of its own is not bought: it is
    returned as something to make. Nothing missing, nothing created.
    """
    from app.modules.purchase_orders.purchase_orders_api import purchase_orders_api

    from .production_service import put_missing_on_shopping_list

    view = await needs_for(
        db, organization_id, date_from=date_from, date_to=date_to, order_id=order_id
    )
    result = OrderMissingResult()
    short = [r for r in view.rows if r.missing > 0]
    result.to_make = [r for r in short if r.action == 'make']
    to_buy = [r for r in short if r.action == 'buy']
    if not to_buy:
        return result

    templates = await core_api.product_templates.get_many_async(
        db, organization_id, [r.template_id for r in to_buy]
    )
    uoms = {
        u.id: u for u in await core_api.uoms.list_for_org_async(db, organization_id)
    }
    by_partner: dict[UUID, list[tuple[NeedRow, _Offer]]] = {}
    unsupplied: list[NeedRow] = []
    today = date.today()
    for row in to_buy:
        template = templates.get(row.template_id)
        if template is None:
            continue
        prices = await purchase_orders_api.list_supplier_prices_for_template_async(
            db, organization_id, row.template_id, active_on=today
        )
        offer = _best_offer(row.missing, template, prices, uoms)
        if offer is None:
            unsupplied.append(row)
        else:
            by_partner.setdefault(offer.partner_id, []).append((row, offer))

    for partner_id, chosen in by_partner.items():
        order = await purchase_orders_api.create_purchase_order_async(
            db,
            organization_id,
            PurchaseOrderCreateInput(
                partner_id=partner_id,
                lines=[
                    PurchaseOrderLineInput(
                        product_template_id=row.template_id,
                        name=row.name,
                        quantity_ordered=offer.quantity,
                        uom_id=offer.uom_id,
                        unit_price=offer.unit_price,
                    )
                    for row, offer in chosen
                ],
            ),
            user.id,
        )
        result.purchase_orders.append(
            OrderedPurchase(
                purchase_order_id=order.id,
                number=order.number,
                partner_id=partner_id,
                lines=[
                    OrderedLine(
                        row.template_id,
                        row.name,
                        offer.quantity,
                        (
                            uoms[offer.uom_id].symbol
                            if offer.uom_id in uoms
                            else row.uom_symbol
                        ),
                    )
                    for row, offer in chosen
                ],
            )
        )

    if unsupplied:
        if await core_api.organizations.is_module_enabled_async(
            db, organization_id, 'shopping_lists'
        ):
            listed = await put_missing_on_shopping_list(
                db,
                organization_id,
                user,
                lang,
                [(r.template_id, r.missing) for r in unsupplied],
            )
            result.shopping_list_added = listed.added_count + listed.raised_count
            result.shopping_list_name = listed.list_name
        else:
            result.unplaced = unsupplied
    return result
