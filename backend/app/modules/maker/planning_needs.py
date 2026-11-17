"""What the planned runs of a period need, what is on hand and on order, and ordering the rest.

The planner's question is not "can this run be made" (``planning_service`` and
completion answer that) but "what do I have to get for next week". This reads
the draft runs of a period — or one run — as one list of needs: per ingredient
what is needed, what the shelf holds once the runs planned before the period
have taken their share, what open purchase orders still expect (with their
dates) and what is still missing.

The list reads the one walk of the queue that the plan's coverage reads
(``planning_service.walk_plan``), so the two cannot disagree about a run. It
stops at the first level of each formula. An ingredient that has a recipe of
its own is something to *make*: what neither the shelf nor a run of it planned
in time covers is proposed as a planned run of that product, never as a
purchase, and its raw materials belong to that run once it is planned.

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

from . import planning_service
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
    #: What draft runs of the ingredient itself make in time for the runs
    #: that ask for it (on their planned day or before it), beyond what the
    #: shelf gave them: a sub-assembly that is planned is not missing.
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


@dataclass
class _Tally:
    """What the runs of the request ask of one ingredient, and where it came from."""

    first_run: ProductionOrder
    has_recipe: bool
    needed: Decimal = Decimal('0')
    in_stock: Decimal = Decimal('0')
    planned: Decimal = Decimal('0')
    unmet: Decimal = Decimal('0')
    scopes: set[UUID | None] = field(default_factory=set)


def _need_row(
    tid: UUID,
    template: ProductTemplateDTO | None,
    uoms: dict[UUID, UomDTO],
    tally: _Tally,
    deliveries: list[ExpectedDelivery],
    purchasing: bool,
) -> NeedRow:
    """One ingredient's row: what the shelf and planned runs left, less what is on its way."""
    on_order = (
        sum((d.quantity for d in deliveries), Decimal('0')) if purchasing else None
    )
    uom = uoms.get(template.uom_id) if template and template.uom_id else None
    return NeedRow(
        template_id=tid,
        name=template.name if template else None,
        uom_symbol=uom.symbol if uom else None,
        needed=tally.needed,
        in_stock=tally.in_stock,
        on_order=on_order,
        expected=deliveries,
        missing=max(Decimal('0'), tally.unmet - (on_order or Decimal('0'))),
        planned=tally.planned,
        action='make' if tally.has_recipe else 'buy',
        needed_by=tally.first_run.production_date,
        output_location_id=tally.first_run.output_storage_location_id,
    )


def _after_earlier_claims(
    deliveries: list[ExpectedDelivery], claimed: Decimal
) -> list[ExpectedDelivery]:
    """What the earlier runs left of the deliveries.

    The runs before the period ask for more than the shelf and the planned
    runs gave them; what is on its way goes to them first, the earliest
    delivery first, as the shelf does.
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
    return left


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
    runs queued before the first of them take their share first — of the
    shelf, of what planned runs make, and what they still lack of the open
    purchase orders — so ``in_stock`` is what is left for the period, not
    what the shelf holds today, and nothing that is on its way is counted
    by two periods.
    """
    ensure_scope(date_from, date_to, order_id)
    walk = await planning_service.walk_plan(db, organization_id)
    view = NeedsView(purchasing=await purchasing_enabled(db, organization_id))
    selected = _selector(date_from, date_to, order_id)
    first = next((i for i, run in enumerate(walk.runs) if selected(run.order)), None)
    if first is None:
        return view

    overflow: dict[UUID, Decimal] = {}
    for run in walk.runs[:first]:
        for claim in run.claims:
            overflow[claim.template_id] = (
                overflow.get(claim.template_id, Decimal('0')) + claim.unmet
            )
    tallies: dict[UUID, _Tally] = {}
    unmeasured: set[UUID] = set()
    for run in walk.runs[first:]:
        if not selected(run.order):
            continue
        view.run_count += 1
        for claim in run.claims:
            if claim.needed is None:
                unmeasured.add(claim.template_id)
                continue
            tally = tallies.setdefault(
                claim.template_id, _Tally(run.order, claim.has_recipe)
            )
            tally.needed += claim.needed
            tally.planned += claim.from_planned
            tally.unmet += claim.unmet
            if run.scope not in tally.scopes:
                # The first run of the period to ask for it in this scope
                # sees the shelf the period opens on.
                tally.scopes.add(run.scope)
                tally.in_stock += claim.on_shelf

    open_lines: list[OpenOrderLineDTO] = (
        await _open_orders(db, organization_id, sorted(tallies))
        if view.purchasing and tallies
        else []
    )
    templates = walk.templates
    for tid in sorted(
        tallies, key=lambda t: templates[t].name if t in templates else ''
    ):
        deliveries = _after_earlier_claims(
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
            overflow.get(tid, Decimal('0')),
        )
        view.rows.append(
            _need_row(
                tid,
                templates.get(tid),
                walk.uoms,
                tallies[tid],
                deliveries,
                view.purchasing,
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
    reached: bool = True  # the shortage reaches the offer's minimum quantity

    @property
    def total(self) -> Decimal:
        return self.quantity * self.unit_price


def _best_offer(
    missing: Decimal,
    template: ProductTemplateDTO,
    prices: list[PartnerPricelistDTO],
    uoms: dict[UUID, UomDTO],
    house_currency: str,
) -> _Offer | None:
    """The cheapest supplier price, compared per stock unit, stated in its own unit.

    Prices are only comparable within one currency, and no rate is held: an
    offer in the organization's own currency comes first, and when nothing is
    quoted in it one other currency is chosen whole (alphabetically), so a
    4.00 in euros never beats 5.00 in zloty on the strength of the number.

    A volume price the shortage does not reach is no price for it: it is
    passed over for the cheapest offer the shortage does reach, and taken
    only when the whole order it forces costs less than that one (or when
    no offer is reached, then the cheapest order in total).

    A supplier sells in its own unit (a 25 kg sack), and the quantity to order
    is the missing quantity expressed in it, put up to a whole step of that
    unit and to the supplier's minimum. An offer in a unit that has no bridge
    to the product's stock unit cannot be compared or ordered and is passed
    over.
    """
    stock_uom = uoms.get(template.uom_id) if template.uom_id else None
    offers: list[_Offer] = []
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
        reached = entry.min_quantity is None or quantity >= entry.min_quantity
        if entry.min_quantity is not None:
            quantity = max(quantity, entry.min_quantity)
        offers.append(
            _Offer(
                entry.partner_id,
                entry.unit_price,
                entry.currency,
                unit_uom,
                quantity,
                per_stock,
                reached,
            )
        )
    if not offers:
        return None
    # One currency whole: the house one if anyone quotes in it.
    currency = min((o.currency for o in offers), key=lambda c: (c != house_currency, c))
    pool = [o for o in offers if o.currency == currency]
    within_reach = [o for o in pool if o.reached]
    best = min(within_reach, key=lambda o: o.per_stock_unit) if within_reach else None
    cheaper = [
        o for o in pool if not o.reached and (best is None or o.total < best.total)
    ]
    return min(cheaper, key=lambda o: o.total) if cheaper else best


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
    """Order what the combined list says is missing: a draft order per supplier and currency.

    Each missing ingredient goes to the supplier whose price is lowest per
    stock unit, in that supplier's unit, the organization's own currency
    first; a supplier quoting in two currencies gets one order for each.
    An ingredient nobody offers goes to
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
    # An order carries one currency, so a supplier quoting in two gets two.
    by_partner: dict[tuple[UUID, str], list[tuple[NeedRow, _Offer]]] = {}
    unsupplied: list[NeedRow] = []
    today = date.today()
    org = await core_api.organizations.get_async(db, organization_id)
    house_currency = (org.currency if org else None) or 'USD'
    for row in to_buy:
        template = templates.get(row.template_id)
        if template is None:
            continue
        prices = await purchase_orders_api.list_supplier_prices_for_template_async(
            db, organization_id, row.template_id, active_on=today
        )
        offer = _best_offer(row.missing, template, prices, uoms, house_currency)
        if offer is None:
            unsupplied.append(row)
        else:
            by_partner.setdefault((offer.partner_id, offer.currency), []).append(
                (row, offer)
            )

    for (partner_id, currency), chosen in by_partner.items():
        order = await purchase_orders_api.create_purchase_order_async(
            db,
            organization_id,
            PurchaseOrderCreateInput(
                partner_id=partner_id,
                currency=currency,
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
