"""Replenishment alerts and the reserve move they propose.

Reads per-location ``ReorderRule`` rows and emits alerts when available
stock at that location drops below its threshold. Before anything is
bought, the alert looks at the reserve shelves of the same warehouse: what
stands there, unreserved and in an active batch, is proposed as an internal
move to the pick face, and only the part reserve cannot cover reaches a
draft purchase order. Reserve is one pool per product and warehouse, shared
by every alert competing for it, so a unit is counted — and promised — once.

Lives in the ``purchase_orders`` module because replenishment is a
procurement decision — and its last mile lives here too:
``create_draft_pos_from_alerts_async`` turns the current alerts into
draft purchase orders, grouped by supplier.  Previously this
service lived in ``warehouse`` and used ``ProductTemplate.min_quantity``
(org-global).  The per-location rules replace that flat field.

The move itself is a warehouse document, so it is created on the other side
of the boundary: ``warehouse.stock_router`` reads the proposal through
``purchase_orders_api`` and posts the transfer through the warehouse's own
one-step door.  Nothing here imports warehouse internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    ReplenishmentAlertDTO,
    ReplenishmentMoveLineDTO,
    ReplenishmentProposalDTO,
    WorkItemDTO,
)
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.modules.purchase_orders import pricelist_service
from app.modules.purchase_orders._service_crud import create_purchase_order
from app.modules.purchase_orders.models import (
    PartnerPricelist,
    PurchaseOrder,
    ReorderRule,
)
from app.modules.purchase_orders.reorder_service import list_for_org_async
from app.modules.purchase_orders.schemas import (
    PurchaseOrderCreate,
    PurchaseOrderLineCreate,
    ReplenishmentDraftSkipped,
)

logger = get_logger(__name__)

#: The location setting that marks a shelf as reserve: stock on it is drawn
#: from to fill pick faces, never replenished by a proposal of its own.
RESERVE_SETTING = 'is_reserve'

#: How many locations one page of the organisation's tree reads.
_LOCATION_PAGE = 1000


def _is_reserve(location: Any) -> bool:
    """Whether a location's settings mark it as a reserve shelf."""
    settings = getattr(location, 'settings', None) or {}
    return settings.get(RESERVE_SETTING) is True


@dataclass(frozen=True)
class _Layout:
    """The organisation's location tree, as the reserve search reads it."""

    locations: dict[UUID, Any]
    #: Each location's top-level location: what makes two shelves one warehouse.
    roots: dict[UUID, UUID | None]
    reserve_ids: set[UUID]

    def in_same_warehouse(self, first: UUID, second: UUID) -> bool:
        root = self.roots.get(first)
        return root is not None and root == self.roots.get(second)


async def _layout_async(db: AsyncSession, org_id: UUID) -> _Layout:
    """Read the whole location tree once, with the reserve shelves in it."""
    locations: dict[UUID, Any] = {}
    offset = 0
    while True:
        page = await core_api.locations.list_async(
            db, org_id, limit=_LOCATION_PAGE, offset=offset
        )
        for storage in page:
            locations[storage.id] = storage
        if len(page) < _LOCATION_PAGE:
            break
        offset += _LOCATION_PAGE

    parents = {storage_id: row.parent_id for storage_id, row in locations.items()}
    roots: dict[UUID, UUID | None] = {}
    for storage_id in locations:
        current: UUID | None = storage_id
        seen: set[UUID] = set()
        while current is not None and current not in seen:
            seen.add(current)
            parent = parents.get(current)
            if parent is None:
                break
            current = parent
        roots[storage_id] = current

    return _Layout(
        locations=locations,
        roots=roots,
        reserve_ids={
            storage_id for storage_id, row in locations.items() if _is_reserve(row)
        },
    )


async def _lots_by_id_async(
    db: AsyncSession, org_id: UUID, template_ids: set[UUID]
) -> dict[UUID, Any]:
    """Every batch of the named products, by id."""
    lots: dict[UUID, Any] = {}
    for template_id in template_ids:
        for lot in await core_api.stock.list_lots_async(db, org_id, template_id):
            lots[lot.id] = lot
    return lots


async def _in_flight_inbound_async(
    db: AsyncSession, org_id: UUID, template_ids: set[UUID]
) -> dict[tuple[UUID, UUID], Decimal]:
    """What transfers have promised into each shelf of the named products.

    A transfer between shelves — including the move this module proposes —
    reserves its stock at confirmation and moves it only on completion, so a
    document waiting for an approval holds goods that are neither on the
    destination shelf nor free at the source. The answer belongs to the
    warehouse module, which owns documents; it is asked for through its
    public API, never read here.
    """
    from app.modules.warehouse.warehouse_api import warehouse_api

    return await warehouse_api.in_flight_inbound_map_async(
        db, org_id, product_template_ids=template_ids
    )


def _lot_is_usable(lot_id: UUID | None, lots: dict[UUID, Any], today: date) -> bool:
    """A batch must be active and unexpired to be drawn from; none always is.

    The status column says nothing about the date — nothing writes EXPIRED
    into it — so a batch past its earliest date is wasted here too, exactly
    as the draw planner treats it.
    """
    if lot_id is None:
        return True
    lot = lots.get(lot_id)
    if lot is None or lot.status != 'active':
        return False
    dates = [day for day in (lot.use_by_date, lot.expiry_date) if day is not None]
    return not dates or min(dates) >= today


def _free(quant: Any) -> Decimal:
    """What a quant holds after the stock promised to documents."""
    return cast(Decimal, quant.quantity - quant.reserved_quantity)


def _available_at_rule_location(
    rule: ReorderRule, quants: list[Any], incoming: Decimal
) -> Decimal:
    """Available stock at the rule's own location, in the product's stock unit.

    *incoming* is what transfers have already promised into the shelf: the
    goods are not there yet, but they are on their way and no longer part of
    a shortage to buy for.
    """
    return incoming + sum(
        (
            _free(quant)
            for quant in quants
            if quant.location_id == rule.storage_location_id
        ),
        Decimal('0'),
    )


def _threshold(rule: ReorderRule) -> Decimal:
    """The level an alert fires under: the minimum or the safety stock, whichever is higher."""
    return max(Decimal(str(rule.min_quantity)), Decimal(str(rule.safety_stock)))


def _suggested_quantity(rule: ReorderRule, available: Decimal) -> Decimal:
    """What brings the location back to its maximum, never below zero."""
    return max(
        max(Decimal(str(rule.max_quantity)), _threshold(rule)) - available,
        Decimal('0'),
    )


def _reserve_by_location(
    rule: ReorderRule,
    quants: list[Any],
    layout: _Layout,
    lots: dict[UUID, Any],
) -> dict[UUID, Decimal]:
    """Eligible reserve stock of the product, per shelf of the same warehouse.

    Only reserve shelves feed a proposal, and a reserve shelf is never
    refilled from another one. Reservations are already taken off by the
    quants; a batch that is not active, or is past its date, is left out
    whole.
    """
    if rule.storage_location_id in layout.reserve_ids:
        return {}
    today = date.today()
    by_location: dict[UUID, Decimal] = {}
    for quant in quants:
        location_id = quant.location_id
        if location_id is None or location_id not in layout.reserve_ids:
            continue
        if location_id == rule.storage_location_id:
            continue
        if not layout.in_same_warehouse(location_id, rule.storage_location_id):
            continue
        if _free(quant) <= 0:
            continue
        if not _lot_is_usable(quant.lot_id, lots, today):
            continue
        by_location[location_id] = by_location.get(location_id, Decimal('0')) + _free(
            quant
        )
    return by_location


def _richest(by_location: dict[UUID, Decimal]) -> UUID | None:
    """The reserve shelf holding the most — the one a proposal draws from.

    Ties are broken by id so two readers of the same stock agree on the shelf.
    """
    if not by_location:
        return None
    return max(by_location.items(), key=lambda row: (row[1], str(row[0])))[0]


@dataclass(frozen=True)
class _Shortage:
    """One alerting rule, before the warehouse's reserve is shared out."""

    rule: ReorderRule
    available: Decimal
    suggested: Decimal
    threshold: Decimal
    by_location: dict[UUID, Decimal]
    #: The top-level location the rule's shelf belongs to; reserve is shared
    #: only inside one warehouse, so this is the pool's other half.
    warehouse_root: UUID | None


def _reserve_shares(shortages: list[_Shortage]) -> dict[UUID, Decimal]:
    """Share each warehouse's reserve among the rules that compete for it.

    Reserve is one finite pool, and two pick faces below their minimum draw
    from the same shelves. A unit promised to both would be bought twice, so
    the rules take turns — in the order the caller read them, which is
    stable — and each takes at most what brings it back to its maximum. What
    no rule claimed is what a draft purchase order is for.

    A rule standing on a reserve shelf of its own has no pool to draw from
    and neither claims nor spends one; it buys what it needs.
    """
    pools: dict[tuple[UUID, UUID | None], Decimal] = {}
    for shortage in shortages:
        if not shortage.by_location:
            continue
        key = (shortage.rule.product_template_id, shortage.warehouse_root)
        pools.setdefault(key, sum(shortage.by_location.values(), Decimal('0')))

    shares: dict[UUID, Decimal] = {}
    for shortage in shortages:
        key = (shortage.rule.product_template_id, shortage.warehouse_root)
        pool = pools.get(key) if shortage.by_location else None
        if pool is None or pool <= 0:
            shares[shortage.rule.id] = Decimal('0')
            continue
        share = min(pool, shortage.suggested)
        shares[shortage.rule.id] = share
        pools[key] = pool - share
    return shares


async def _shortages_async(
    db: AsyncSession,
    org_id: UUID,
    rules: list[ReorderRule],
) -> tuple[list[_Shortage], _Layout, dict[UUID, Any]]:
    """The alerting rules with what each needs, and the tree and lots read."""
    # Load the quants (the records' view) of every template the rules name.
    template_ids = {rule.product_template_id for rule in rules}
    quants_by_template: dict[UUID, list[Any]] = {tid: [] for tid in template_ids}
    for tid in template_ids:
        quants_by_template[tid] = list(
            await core_api.stock.list_quants_async(db, org_id, product_template_id=tid)
        )
    # The reserve search reads the tree and the batches once for every rule.
    layout = await _layout_async(db, org_id)
    lots = await _lots_by_id_async(db, org_id, template_ids)
    # A transfer that is already in flight holds its goods at the source and
    # has not moved them yet, so the pick face's records still read short.
    # What it promised is no longer part of the shortage: without that, the
    # same proposal acted on twice would carry the stock twice.
    in_flight = await _in_flight_inbound_async(db, org_id, template_ids)

    shortages: list[_Shortage] = []
    for rule in rules:
        if rule.min_quantity <= 0:
            # MIN is the threshold that makes a rule fire, so a rule at 0 has
            # nothing to fire on. The API refuses to write one; a row from
            # before that says so out loud rather than vanishing from the
            # answer, because on the list it looks like every other rule.
            logger.warning(
                'Reorder rule %s has no minimum threshold (%s) and cannot '
                'fire — set a minimum above zero.',
                rule.id,
                rule.min_quantity,
            )
            continue

        quants = quants_by_template.get(rule.product_template_id, [])
        total_available = _available_at_rule_location(
            rule,
            quants,
            in_flight.get(
                (rule.storage_location_id, rule.product_template_id), Decimal('0')
            ),
        )
        # The rule promises stock never falls below the safety stock, and
        # the form says so in every language: the threshold the alert
        # fires on is whichever of the two stands higher.
        threshold = _threshold(rule)
        if total_available >= threshold:
            continue
        shortages.append(
            _Shortage(
                rule=rule,
                available=total_available,
                suggested=_suggested_quantity(rule, total_available),
                threshold=threshold,
                by_location=_reserve_by_location(rule, quants, layout, lots),
                warehouse_root=layout.roots.get(rule.storage_location_id),
            )
        )
    return shortages, layout, lots


async def _compute_alerts_for_rules(
    db: AsyncSession,
    org_id: UUID,
    rules: list[ReorderRule],
) -> list[ReplenishmentAlertDTO]:
    """Alert rows for *rules* whose available stock is below minimum."""
    shortages, _, _ = await _shortages_async(db, org_id, rules)
    shares = _reserve_shares(shortages)

    # A rule with no preferred supplier still has a supplier when the price
    # list names one: the cheapest current offer is proposed, so the alert
    # does not read "No supplier" beside a price the module itself holds.
    # The rule's own choice always wins.
    # The supplier is chosen against what this rule will really order, so a
    # volume price counts only for the rule whose order reaches it.
    wanted = {
        (
            s.rule.product_template_id,
            max(s.suggested - shares.get(s.rule.id, Decimal('0')), Decimal('0')),
        )
        for s in shortages
        if not s.rule.preferred_partner_id
    }
    offers = (
        await pricelist_service.cheapest_offers_async(
            db,
            org_id,
            wanted,
            active_on=await core_api.organizations.today_async(db, org_id),
        )
        if wanted
        else {}
    )

    alerts: list[ReplenishmentAlertDTO] = []
    for shortage in shortages:
        rule = shortage.rule
        by_location = shortage.by_location
        richest = _richest(by_location)
        # One move draws from one shelf — the richest — of the part of the
        # pool this rule claimed; the shelves together are what says how
        # much still has to be bought.
        share = shares.get(rule.id, Decimal('0'))
        proposed = (
            min(share, by_location[richest]) if richest is not None else Decimal('0')
        )
        remaining = max(shortage.suggested - share, Decimal('0'))
        product = rule.product_template
        supplier = rule.preferred_partner
        proposed_offer = (
            None
            if rule.preferred_partner_id
            else offers.get((rule.product_template_id, remaining))
        )
        if proposed_offer is not None:
            supplier = proposed_offer.partner
        alerts.append(
            ReplenishmentAlertDTO(
                reorder_rule_id=rule.id,
                product_template_id=rule.product_template_id,
                product_name=product.name if product else '',
                sku=(product.sku or '') if product else '',
                location_id=rule.storage_location_id,
                available_quantity=float(shortage.available),
                min_quantity=float(Decimal(str(rule.min_quantity))),
                max_quantity=float(rule.max_quantity),
                safety_stock=float(rule.safety_stock),
                shortage=float(shortage.threshold - shortage.available),
                suggested_reorder_quantity=float(shortage.suggested),
                reserve_available_quantity=float(
                    sum(by_location.values(), Decimal('0'))
                ),
                proposed_move_quantity=float(proposed),
                remaining_to_buy=float(remaining),
                preferred_partner_id=supplier.id if supplier else None,
                preferred_partner_name=supplier.name if supplier else None,
            )
        )

    return alerts


async def get_replenishment_alerts(
    db: AsyncSession,
    org_id: UUID,
) -> list[ReplenishmentAlertDTO]:
    """Find product+location pairs where available stock < min_quantity.

    Each ``ReorderRule`` defines the threshold for one
    (product, location) pair.  An alert is emitted when available
    stock at that location falls below ``rule.min_quantity`` or below
    ``rule.safety_stock`` — whichever stands higher, the safety stock
    being the floor the rule promises — regardless of stock
    elsewhere.

    Returns a list of ``ReplenishmentAlertDTO`` with: reorder_rule_id,
    product_template_id, product_name, sku, storage_location_id,
    available_quantity, min_quantity, shortage, max_quantity,
    safety_stock, suggested_reorder_quantity, reserve_available_quantity,
    proposed_move_quantity, remaining_to_buy, preferred_partner_id,
    preferred_partner_name.
    """
    rules = await list_for_org_async(db, org_id)
    if not rules:
        return []
    return await _compute_alerts_for_rules(db, org_id, rules)


async def replenishment_work_items_async(
    db: AsyncSession, org_id: UUID
) -> list[WorkItemDTO]:
    """The reserve moves the current alerts propose, as To do tasks.

    One task per alert whose reserve can cover part of the shortage. It is
    derived on every read, so a proposal nobody acted on expires with the
    next recomputation — nothing is stored to pile up.
    """
    rules = await list_for_org_async(db, org_id)
    if not rules:
        return []
    rule_by_id = {rule.id: rule for rule in rules}
    items: list[WorkItemDTO] = []
    for alert in await _compute_alerts_for_rules(db, org_id, rules):
        if alert.proposed_move_quantity <= 0:
            continue
        rule = rule_by_id[alert.reorder_rule_id]
        target = rule.storage_location
        items.append(
            WorkItemDTO(
                kind='replenish',
                source_kind='replenishment',
                source_id=rule.id,
                subject=alert.product_name,
                count=Decimal(str(alert.proposed_move_quantity)),
                unit=rule.uom_symbol,
                place=target.name if target is not None else None,
                next_action='replenish',
                action_href=f'/warehouse/todo?replenish={rule.id}',
            )
        )
    items.sort(key=lambda item: (item.subject or '', str(item.source_id)))
    return items


def _line_for_item(
    item: Any,
    rule: ReorderRule,
    lots: dict[UUID, Any],
    source_id: UUID,
    source_name: str,
    quantity: Decimal,
) -> ReplenishmentMoveLineDTO:
    """One record, as the transfer line that carries it to the pick face."""
    lot = lots.get(item.lot_id) if item.lot_id is not None else None
    return ReplenishmentMoveLineDTO(
        item_id=item.id,
        product_template_id=rule.product_template_id,
        product_name=item.template_name or item.name,
        lot_id=item.lot_id,
        lot_name=lot.name if lot is not None else None,
        expiry_date=(lot.expiry_date if lot is not None else None) or item.expiry_date,
        source_location_id=source_id,
        source_location_name=source_name,
        quantity=quantity,
        uom_id=item.uom_id,
        uom_symbol=item.uom_symbol,
    )


async def _lines_from_shelf_async(
    db: AsyncSession,
    org_id: UUID,
    rule: ReorderRule,
    lots: dict[UUID, Any],
    layout: _Layout,
    source_id: UUID,
    quantity: Decimal,
) -> list[ReplenishmentMoveLineDTO]:
    """Carry *quantity* off one reserve shelf, oldest batch first.

    The draw planner decides which records give and in what order — the same
    FEFO order a take off that shelf would use, so the prepared sheet asks
    for exactly the stock a draw would pick: oldest date across records and
    batches together, reservations already off, inactive batches left out.
    """
    draws = await core_api.stock.plan_draw_async(
        db,
        org_id,
        rule.product_template_id,
        source_id,
        quantity,
        removal_strategy='FEFO',
        any_owner=True,
        by_record=True,
    )
    if not draws:
        return []
    records = {
        item.id: item
        for item in await core_api.locations.list_items_in_location_async(
            db, org_id, source_id
        )
    }
    source_name = layout.locations[source_id].name
    lines: list[ReplenishmentMoveLineDTO] = []
    for draw in draws:
        item = records.get(draw.record_id) if draw.record_id is not None else None
        if item is None:
            continue
        lines.append(
            _line_for_item(item, rule, lots, source_id, source_name, draw.consumed)
        )
    return lines


async def get_reserve_move_plan_async(
    db: AsyncSession, org_id: UUID, rule: ReorderRule
) -> ReplenishmentProposalDTO:
    """The internal move this rule's alert proposes, from the richest reserve shelf.

    The plan is re-derived from live stock every time: a proposal is never
    stored, so one nobody acted on disappears with the shortage it answered.
    A shelf back at or above its threshold has no shortage left, and the
    sheet that showed it carries nothing — posting it is refused rather than
    carrying stock the pick face no longer asks for.

    The quantity is what this rule claimed of the warehouse's reserve, not
    the whole rack: another pick face short of the same product may hold the
    rest of that pool, and a move that took it all would take its share too.
    """
    # Reserve is shared per product and warehouse, so the product's other
    # rules are read as well; that is also what makes the proposal expire
    # when this rule's own shortage ends.
    pool_rules = await list_for_org_async(
        db, org_id, product_template_id=rule.product_template_id
    )
    shortages, layout, lots = await _shortages_async(db, org_id, pool_rules)
    share = _reserve_shares(shortages).get(rule.id, Decimal('0'))
    shortage = next((row for row in shortages if row.rule.id == rule.id), None)
    source_id = _richest(shortage.by_location) if shortage is not None else None
    quantity = (
        min(share, shortage.by_location[source_id])
        if shortage is not None and source_id is not None
        else Decimal('0')
    )
    lines = (
        await _lines_from_shelf_async(
            db, org_id, rule, lots, layout, source_id, quantity
        )
        if source_id is not None and quantity > 0
        else []
    )
    target = rule.storage_location
    return ReplenishmentProposalDTO(
        reorder_rule_id=rule.id,
        product_template_id=rule.product_template_id,
        product_name=rule.product_name,
        target_location_id=rule.storage_location_id,
        target_location_name=target.name if target is not None else '',
        quantity=sum((line.quantity for line in lines), Decimal('0')),
        unit=rule.uom_symbol,
        lines=lines,
    )


def _best_offer(
    entries: list[PartnerPricelist], quantity: Decimal
) -> PartnerPricelist | None:
    """Cheapest valid offer for *quantity*, preferring a reached tier.

    ``entries`` comes pre-ordered by unit price (the pricelist service
    contract), so the first tier the order quantity reaches is also the
    cheapest one reached.
    """
    if not entries:
        return None
    tier_matches = [
        e for e in entries if e.min_quantity is not None and e.min_quantity <= quantity
    ]
    if tier_matches:
        return tier_matches[0]
    return entries[0]


async def _load_rules_by_ids(
    db: AsyncSession, org_id: UUID, rule_ids: list[UUID]
) -> dict[UUID, ReorderRule]:
    """The org's rules among *rule_ids*, keyed by id (others are absent)."""
    rows = await db.scalars(
        select(ReorderRule).where(
            ReorderRule.organization_id == org_id,
            ReorderRule.id.in_(rule_ids),
        )
    )
    return {rule.id: rule for rule in rows.all()}


async def create_draft_pos_from_alerts_async(
    db: AsyncSession,
    org_id: UUID,
    rule_ids: list[UUID],
    user_id: UUID,
) -> tuple[list[PurchaseOrder], list[ReplenishmentDraftSkipped]]:
    """Turn the current alerts of *rule_ids* into draft purchase orders.

    The alerts are re-derived from live stock — the quantities a client
    rendered minutes ago are not trusted. Each supplier group becomes one
    DRAFT PO (normal editable order: number, audit, PATCH-able lines)
    whose lines carry ``source_reorder_rule_id`` back to the rule. A line is
    for what reserve cannot cover; a rule a reserve move covers in full is
    reported as such, and a rule without a preferred supplier is reported,
    never made an empty order.

    Returns ``(created_pos, skipped)``; does not commit — the caller does.
    """
    rules_by_id = await _load_rules_by_ids(db, org_id, rule_ids)
    skipped: list[ReplenishmentDraftSkipped] = [
        ReplenishmentDraftSkipped(reorder_rule_id=rule_id, reason='not_found')
        for rule_id in rule_ids
        if rule_id not in rules_by_id
    ]
    # Keep the caller's order so groups and lines are deterministic.
    rules = [rules_by_id[rule_id] for rule_id in rule_ids if rule_id in rules_by_id]

    # Reserve is one pool per product and warehouse, and a rule outside this
    # batch competes for it too. The remainder is therefore computed against
    # every rule of the product, not only the ones being ordered — two batches
    # must not each count the same shelf and buy nothing for it.
    pool_rules: list[ReorderRule] = []
    for product_id in sorted({rule.product_template_id for rule in rules}, key=str):
        pool_rules.extend(
            await list_for_org_async(db, org_id, product_template_id=product_id)
        )
    alerts = await _compute_alerts_for_rules(db, org_id, pool_rules)
    alert_by_rule = {alert.reorder_rule_id: alert for alert in alerts}

    groups: dict[UUID, list[tuple[ReorderRule, ReplenishmentAlertDTO]]] = {}
    for rule in rules:
        alert = alert_by_rule.get(rule.id)
        if alert is None:
            skipped.append(
                ReplenishmentDraftSkipped(
                    reorder_rule_id=rule.id,
                    product_name=rule.product_name,
                    reason='not_alerting',
                )
            )
            continue
        remainder = alert.remaining_to_buy
        if remainder is not None and remainder <= 0:
            skipped.append(
                ReplenishmentDraftSkipped(
                    reorder_rule_id=rule.id,
                    product_name=rule.product_name,
                    reason='covered_by_reserve',
                )
            )
            continue
        # The alert's supplier is the rule's own choice or, failing that, the
        # one the price list names — the same one the alerts view showed.
        partner_id = alert.preferred_partner_id
        if partner_id is None:
            skipped.append(
                ReplenishmentDraftSkipped(
                    reorder_rule_id=rule.id,
                    product_name=rule.product_name,
                    reason='no_supplier',
                )
            )
            continue
        groups.setdefault(partner_id, []).append((rule, alert))

    today = await core_api.organizations.today_async(db, org_id)
    created: list[PurchaseOrder] = []
    for partner_id, members in groups.items():
        offers = await pricelist_service.list_for_partner_async(
            db, org_id, partner_id, active_on=today
        )
        offers_by_template: dict[UUID, list[PartnerPricelist]] = {}
        for entry in offers:
            offers_by_template.setdefault(entry.product_template_id, []).append(entry)

        lines: list[PurchaseOrderLineCreate] = []
        currencies: set[str] = set()
        for rule, alert in members:
            remainder = alert.remaining_to_buy
            quantity = Decimal(
                str(
                    remainder
                    if remainder is not None
                    else alert.suggested_reorder_quantity
                )
            )
            offer = _best_offer(
                offers_by_template.get(rule.product_template_id, []), quantity
            )
            unit_price = None
            uom_id = rule.uom_id
            if offer is not None:
                # The pricelist stores 4 decimal places, an order line 2.
                unit_price = offer.unit_price.quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                )
                currencies.add(offer.currency)
                uom_id = offer.uom_id or uom_id
            lines.append(
                PurchaseOrderLineCreate(
                    product_template_id=rule.product_template_id,
                    name=rule.product_name,
                    quantity_ordered=quantity,
                    unit_price=unit_price,
                    uom_id=uom_id,
                    source_reorder_rule_id=rule.id,
                )
            )

        po = await create_purchase_order(
            db,
            org_id,
            PurchaseOrderCreate(
                partner_id=partner_id,
                lines=lines,
                # A line carries no currency — one shared by every priced
                # line becomes the order's; a mix falls back to the org's.
                currency=currencies.pop() if len(currencies) == 1 else None,
            ),
            user_id,
        )
        created.append(po)

    return created, skipped
