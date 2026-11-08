"""Production order service — consumes ingredients, produces output, audits.

Atomic transaction pattern (canonical receipt, derived from
``warehouse/_stock_executor_receipt.py:159-201``):
  1. Resolve multi-level BOM to a flat list of (child, qty, unit).
  2. Consume, then compute total input cost from what the layers gave up.
  3. Cross-location consume: ingredients may be in different locations.
     ``stock_consumption.consume_across_locations`` honours per-template
     FIFO/FEFO and hard-fails on deficit (no partial consume on rollback).
  4. Create the output Item (1 per order = a single production batch).
  5. Post the output's movement at the output location.
  6. Record the valuation receipt for the output (unit_cost = cost / qty).
  7. Persist a ``ProductionOrderLine`` snapshot per consumed ingredient.
  8. Stamp the order COMPLETED.

Hard-fail contract preserved throughout: the Core API never commits, so
any raise rolls back the entire production.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    ItemAction,
    ItemCreateDTO,
    ShoppingListItemCreateDTO,
    UserContextDTO,
)
from app.core.cost_estimates import UnitCostEstimate
from app.core.db_utils import paginate_async
from app.core.exceptions import EntityNotFoundError, ServiceRejectionError
from app.core.logging import get_logger
from app.core.money import quantise
from app.core.public_api import core_api
from app.i18n import Language

from . import bom_service, recipe_service, stock_consumption
from ._schemas_production import (
    ProductionOrderCreate,
    ProductionOrderUpdate,
    ProductionPreviewResponse,
    ShortageShoppingListResponse,
)
from ._schemas_recipes import IngredientAvailabilityItem
from ._valuation_batch import fetch_estimates_batch
from .models import MakerRecipe, ProductionOrder, ProductionOrderLine

logger = get_logger(__name__)


async def get_order(
    db: AsyncSession, organization_id: UUID, order_id: UUID
) -> ProductionOrder | None:
    """Fetch a production order by id, scoped to the organization."""
    result = await db.execute(
        select(ProductionOrder).where(
            ProductionOrder.organization_id == organization_id,
            ProductionOrder.id == order_id,
        )
    )
    return result.scalar_one_or_none()


async def list_lines(
    db: AsyncSession,
    organization_id: UUID,
    order_id: UUID,
) -> list[ProductionOrderLine]:
    """Return all ProductionOrderLine rows for a given order, scoped to org."""
    result = await db.execute(
        select(ProductionOrderLine)
        .join(
            ProductionOrder,
            ProductionOrderLine.production_order_id == ProductionOrder.id,
        )
        .where(
            ProductionOrder.organization_id == organization_id,
            ProductionOrderLine.production_order_id == order_id,
        )
    )
    return list(result.scalars().all())


async def list_orders(
    db: AsyncSession,
    organization_id: UUID,
    output_template_id: UUID | None = None,
    status: str | None = None,
    *,
    sort: str = 'newest',
    date_from: date | None = None,
    date_to: date | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[ProductionOrder], int]:
    """List production orders with optional filters, sorting, and pagination.

    Returns ``(items, total)`` so the router can build a paginated envelope.
    ``sort`` is one of: newest, oldest, cost_desc. Date range applies to
    ``created_at`` (inclusive on both ends).
    """
    base_where = [ProductionOrder.organization_id == organization_id]
    if output_template_id is not None:
        base_where.append(ProductionOrder.output_template_id == output_template_id)
    if status is not None:
        base_where.append(ProductionOrder.status == status)
    if date_from is not None:
        base_where.append(ProductionOrder.created_at >= date_from)
    if date_to is not None:
        base_where.append(ProductionOrder.created_at <= date_to)

    stmt = select(ProductionOrder).where(*base_where)
    if sort == 'oldest':
        stmt = stmt.order_by(ProductionOrder.created_at.asc())
    elif sort == 'cost_desc':
        stmt = stmt.order_by(ProductionOrder.total_cost.desc().nullslast())
    else:
        stmt = stmt.order_by(ProductionOrder.created_at.desc())

    return await paginate_async(db, stmt, limit=limit, offset=offset)


class _MonthBucket(TypedDict):
    result: Decimal
    orders: int


async def monthly_result(
    db: AsyncSession,
    organization_id: UUID,
    months: int = 6,
) -> list[dict[str, str | Decimal | int]]:
    """Aggregate the monthly financial result from order snapshots.

    For every COMPLETED order with a result snapshot, the month outcome is
    ``result_per_unit × actual_qty`` (fallback to ``planned_qty``). Returns
    one entry per calendar month, oldest → newest, including zero months for
    chart continuity:

        [{'month': '2026-08', 'result': Decimal('123.45'), 'orders': 2}, ...]
    """
    # Which month a run belongs to is a question about the organization's
    # calendar, not the server's: a run completed at one in the morning on the
    # local first of the month fell into the previous month for every
    # organization east of the server, and the window itself opened a day off.
    tz = await core_api.organizations.timezone_async(db, organization_id)
    today = await core_api.organizations.today_async(db, organization_id)
    first_day = today.replace(day=1)
    year, month = first_day.year, first_day.month
    for _ in range(months - 1):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    start = datetime.combine(date(year, month, 1), datetime.min.time(), tzinfo=tz)

    result = await db.execute(
        select(
            ProductionOrder.completed_at,
            ProductionOrder.result_per_unit,
            ProductionOrder.actual_qty,
            ProductionOrder.planned_qty,
        ).where(
            ProductionOrder.organization_id == organization_id,
            ProductionOrder.status == 'COMPLETED',
            ProductionOrder.completed_at.is_not(None),
            ProductionOrder.completed_at >= start,
            ProductionOrder.result_per_unit.is_not(None),
        )
    )
    rows = result.all()

    # Month bucket labels for the whole window (including empty months).
    buckets: dict[str, _MonthBucket] = {}
    cur_year, cur_month = year, month
    for _ in range(months):
        key = f'{cur_year:04d}-{cur_month:02d}'
        buckets[key] = {'result': Decimal('0'), 'orders': 0}
        cur_month += 1
        if cur_month == 13:
            cur_month = 1
            cur_year += 1

    for row in rows:
        completed_at = row.completed_at.astimezone(tz)
        key = f'{completed_at.year:04d}-{completed_at.month:02d}'
        bucket = buckets.setdefault(key, {'result': Decimal('0'), 'orders': 0})
        effective_qty = row.actual_qty or row.planned_qty
        if effective_qty and effective_qty > 0:
            bucket['result'] += row.result_per_unit * effective_qty
        bucket['orders'] += 1

    return [
        {
            'month': key,
            'result': quantise(value['result']),
            'orders': value['orders'],
        }
        for key, value in sorted(buckets.items())
    ]


PR_DOC_TYPE = 'PR'
#: The width already printed on production runs, and the only part of the
#: number this module still states. The register's own default is three
#: digits, and "PR/2026/0007" beside "PR/2026/008" is the kind of history a
#: register should not carry. The rest of the shape is the organization's and
#: travels with its profile the way an order's does.
PR_NUMBER_WIDTH = 4


async def _highest_pr_number_async(db: AsyncSession, org_id: UUID, prefix: str) -> int:
    """The largest sequence already printed on a run under *prefix*.

    Runs are not documents, so the numbering engine cannot find its own floor
    for them — it counts the ``documents`` table. Without this, an organization
    a year into its register would be offered number one again and the unique
    index would refuse the order.
    """
    from app.modules.warehouse.warehouse_api import warehouse_api

    numbers = await db.scalars(
        select(ProductionOrder.number).where(
            ProductionOrder.organization_id == org_id,
            ProductionOrder.number.like(f'{prefix}%'),
        )
    )
    # Legacy rows carry NULL, and the type says so even though a NULL never
    # matches the prefix — the sequence counts only what is actually printed.
    printed = [number for number in numbers.all() if number is not None]
    return warehouse_api.highest_sequence(printed, prefix)


async def _next_order_number(db: AsyncSession, organization_id: UUID) -> str:
    """Next run number from the organization's document register.

    Through the document numbering engine: it holds the advisory lock, the
    persistent counter and the year rule — the same one every document gets,
    and it counts in UTC: a run started an hour after midnight on the local
    first of January is numbered into the year the register says, not the one
    the window shows.

    This used to be a second engine beside it — its own lock, its own prefix
    scan, the shape ``PR/{year}/{seq}`` hardcoded — so an organization that
    changed how its documents are numbered saw the change everywhere except on
    its runs. That engine and its hardcoded shape are gone. What the earlier
    decision asked for stands: the number is one a person can say out loud.
    """
    from app.modules.warehouse.warehouse_api import warehouse_api

    return await warehouse_api.generate_number_async(
        db,
        organization_id,
        PR_DOC_TYPE,
        highest_in_use=lambda prefix: _highest_pr_number_async(
            db, organization_id, prefix
        ),
        sequence_width=PR_NUMBER_WIDTH,
    )


async def create_order(
    db: AsyncSession,
    organization_id: UUID,
    data: ProductionOrderCreate,
    user: UserContextDTO,
) -> ProductionOrder:
    """Persist a new DRAFT order. ``complete_production`` fulfils it later.

    Resolves the recipe: uses ``data.recipe_id`` if provided, otherwise
    looks up the default recipe for ``output_template_id``.  If no recipe exists,
    raises ``ServiceRejectionError`` (translated by the 400 handler, with the
    reader's language claimed honestly).

    respects ``create_on_shortage_strategy`` — ALLOW creates
    always; WARN raises ``ShortageWarning`` (caller returns warning info);
    BLOCK raises ``ShortageBlocked`` (422 before DRAFT is created).
    """
    # Resolve recipe.
    if data.recipe_id is not None:
        # Validate the provided recipe_id belongs to this org + template.
        # Locked: the recipe is checked and then an order is created from it in
        # the same transaction, and nothing serialises order creation any more —
        # the numbering engine holds its own lock on the counter, not on this.
        result = await db.execute(
            select(MakerRecipe)
            .where(
                MakerRecipe.organization_id == organization_id,
                MakerRecipe.id == data.recipe_id,
            )
            .with_for_update()
        )
        recipe = result.scalar_one_or_none()
        if recipe is None:
            raise ServiceRejectionError(
                'production_recipe_not_found', recipe_id=data.recipe_id
            )
        if recipe.output_template_id != data.output_template_id:
            raise ServiceRejectionError('production_recipe_product_mismatch')
        resolved_recipe_id = recipe.id
    else:
        recipe = await bom_service.find_default_recipe(
            db, organization_id, data.output_template_id
        )
        if recipe is None:
            raise ServiceRejectionError('production_no_recipe')
        resolved_recipe_id = recipe.id

    # check shortage strategy at create-time. The shortage is
    # computed once regardless of the strategy — Warn uses it to warn,
    # Block to refuse, and Allow still records the fact on the order, so
    # the refusal dialog later can tell "never satisfiable" from "ran out
    # since the draft was created" instead of guessing history.
    settings = await recipe_service.get_settings(db, organization_id, for_update=True)
    from .availability_service import compute_shortage_list, resolve_check_location

    check_location_id = await resolve_check_location(
        db,
        organization_id,
        context_location_id=data.output_location_id,
    )
    shortages = await compute_shortage_list(
        db,
        organization_id,
        resolved_recipe_id,
        data.planned_qty,
        location_id=check_location_id,
    )
    if (
        settings.create_on_shortage_strategy != 'ALLOW'
        and shortages
        and not data.confirm_shortage
    ):
        from .exceptions import ShortageBlockedError, ShortageWarningError

        if settings.create_on_shortage_strategy == 'BLOCK':
            raise ShortageBlockedError(shortages)
        elif settings.create_on_shortage_strategy == 'WARN':
            raise ShortageWarningError(shortages)

    obj = ProductionOrder(
        organization_id=organization_id,
        number=await _next_order_number(db, organization_id),
        output_template_id=data.output_template_id,
        recipe_id=resolved_recipe_id,
        planned_qty=data.planned_qty,
        output_storage_location_id=data.output_location_id,
        production_date=data.production_date,
        notes=data.notes,
        created_by=user.id,
        status='DRAFT',
        short_at_create=bool(shortages),
    )
    db.add(obj)
    await db.flush()
    await _journal_opened(db, obj, user)
    return obj


async def _journal_opened(
    db: AsyncSession,
    order: ProductionOrder,
    user: UserContextDTO,
    copied_from: str | None = None,
) -> None:
    """Opening an order is an event of its own — the same record the cancel
    entry points back at. A draft that was never fulfilled should be
    readable in the log as "planned, then dropped", not as silence; a copy
    names the order it was copied from."""
    output = await core_api.product_templates.get_async(
        db, order.organization_id, order.output_template_id
    )
    snapshot: dict[str, object] = {
        'name': order.number,
        'status': 'DRAFT',
        'output': output.name if output else None,
        'planned_qty': str(_stored_qty(order.planned_qty)),
    }
    if copied_from is not None:
        snapshot['copied_from'] = copied_from
    await core_api.audit_log.log_action_async(
        db,
        organization_id=order.organization_id,
        user_id=user.id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.MAKER_PRODUCTION_ORDER,
        target_id=order.id,
        snapshot=snapshot,
    )


def _stored_qty(qty: Decimal) -> Decimal:
    """A quantity as the column keeps it (``Numeric(12, 3)``), so the journal
    records the digits the database holds, not the ones a form posted."""
    return quantise(qty, 3)


def _plan_shape(order: ProductionOrder) -> dict[str, object]:
    """The fields a draft's edit can move. A quantity stays a ``Decimal`` so
    comparing it is numeric (``4`` and ``4.000`` are one quantity); the
    journal writes it down as exact digits."""
    return {
        'planned_qty': _stored_qty(order.planned_qty),
        'production_date': (
            order.production_date.isoformat() if order.production_date else None
        ),
        'notes': order.notes,
    }


async def _recipe_name(
    db: AsyncSession, organization_id: UUID, recipe_id: UUID | None
) -> str | None:
    """Name of a recipe, for error messages. ``None`` when there is no recipe."""
    if recipe_id is None:
        return None
    result = await db.execute(
        select(MakerRecipe.name).where(
            MakerRecipe.id == recipe_id,
            MakerRecipe.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def _lock_draft_order(
    db: AsyncSession, organization_id: UUID, order_id: UUID
) -> ProductionOrder:
    """Load the order FOR UPDATE and refuse anything that is not a DRAFT.

    The status guard is a read-modify-write transition, so concurrent
    completes must serialize (TOCTOU guard).
    """
    result = await db.execute(
        select(ProductionOrder)
        .where(
            ProductionOrder.organization_id == organization_id,
            ProductionOrder.id == order_id,
        )
        .with_for_update()
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise EntityNotFoundError(
            'production_order', f'Production order {order_id} not found'
        )
    if order.status != 'DRAFT':
        # A double-tap on "complete" is an ordinary day, not a programming
        # mistake: the status the order actually carries explains the
        # refusal, and it answers in the reader's language.
        raise ServiceRejectionError(
            'production_complete_not_draft', status=order.status
        )
    return order


async def _resolve_actual_qty(
    db: AsyncSession,
    organization_id: UUID,
    order: ProductionOrder,
    actual_qty: Decimal | None,
) -> Decimal:
    """Default to planned, refuse zero, gate overproduction by setting."""
    if actual_qty is None:
        actual_qty = order.planned_qty

    # actual_qty must be > 0. The request schema allows 0 (`ge=0` — a
    # zero output used to mean "cancel"), so this refusal is reachable.
    if actual_qty <= 0:
        raise ServiceRejectionError('production_actual_qty_must_be_positive')

    settings = await recipe_service.get_settings(db, organization_id, for_update=True)
    if actual_qty > order.planned_qty and not settings.allow_overproduction:
        raise ServiceRejectionError('production_overproduction_disabled')
    return actual_qty


async def _explode_planned_consumption(
    db: AsyncSession, organization_id: UUID, order: ProductionOrder
) -> list[tuple[UUID, Decimal, str]]:
    """Explode what the run consumes: full planned consumption.

    **A run consumes by a fresh expansion, not by frozen lines.** This is
    called from ``complete_production``, at the moment the order closes, and
    it reads the recipe as it stands then; the ``ProductionOrderLine`` rows
    are written afterwards by ``_write_order_lines``, as a record of what
    happened rather than a plan the run follows. So editing a BOM line while
    an order is open changes what that order will take off the shelf — which
    is why every recipe and BOM-line write leaves a journal entry
    (``recipe_service.log_recipe_change``): without one, the formula could
    move under an open order and nothing would say so.

    Recipe-aware top-level explosion: when the order references an explicit
    recipe, consumption uses THAT recipe's lines (previously the default
    recipe was used here while fixed costs read order.recipe_id — the two
    could diverge). Nested sub-assemblies keep the default-recipe lookup
    (documented design).

    Quantities come back **in each ingredient's stock unit**, converted here so
    that consumption, cost and the order lines cannot disagree about what the
    number means. They used to come back in the recipe line's unit and be
    passed straight to the ledger, which knows nothing about units: a line
    reading 500 g against stock kept in kilograms passed the availability check
    — that one converts — and then took 500 kg off the shelf. The valuation
    layers, the history and every later count carried the inflated figure, and
    a shelf too small for it failed hard against a check that had just said
    yes. This was the only place the application actively falsified
    authoritative stock.
    """
    flat = await bom_service.explode_in_stock_units(
        db,
        organization_id,
        order.output_template_id,
        order.planned_qty,
        recipe_id=order.recipe_id,
    )

    # A run that explodes to nothing would still create the output item and
    # put it on the shelf — goods produced out of thin air against zero
    # consumption. Refuse before anything is touched; the recipe has to list
    # what the run consumes first.
    if not flat:
        from .exceptions import EmptyBillOfMaterialsError

        raise EmptyBillOfMaterialsError(
            order.recipe_id,
            await _recipe_name(db, organization_id, order.recipe_id),
        )
    return flat


async def _assert_stock_is_available(
    db: AsyncSession,
    organization_id: UUID,
    order: ProductionOrder,
    check_location_id: UUID | None,
    *,
    record_shortfall: bool = False,
) -> None:
    """pre-check for shortages BEFORE consuming anything.

    *check_location_id* arrives resolved — the same value the draw below
    consumes under, decided once by the caller so the two doors cannot
    disagree. If any ingredient is short, raise 422 with the actionable
    shortage list instead of letting consume_across_locations fail
    mid-transaction. Legacy orders without a recipe snapshot (recipe_id=None,
    pre-0a) skip the pre-check and keep the historical behaviour.
    """
    if order.recipe_id is None:
        return

    from .availability_service import compute_shortage_list
    from .exceptions import InsufficientStockError

    shortages = await compute_shortage_list(
        db,
        organization_id,
        order.recipe_id,
        order.planned_qty,
        location_id=check_location_id,
    )
    if record_shortfall:
        # A run that already happened used the goods, so a shortage is the
        # records being wrong, not a reason to refuse. A line nobody can
        # measure against its stock is still refused: what to take off the
        # shelf for it cannot be told.
        shortages = [item for item in shortages if item.shortage is None]
    if shortages:
        raise InsufficientStockError(shortages, short_at_create=order.short_at_create)


async def _fixed_cost_and_recipe(
    db: AsyncSession, organization_id: UUID, order: ProductionOrder
) -> tuple[Decimal, MakerRecipe | None]:
    """Fixed cost lines: Σ amount × batches.

    The recipe row travels back with the total — the result snapshot
    needs it.
    """
    if order.recipe_id is None:
        return Decimal('0'), None

    recipe_result = await db.execute(
        select(MakerRecipe).where(
            MakerRecipe.id == order.recipe_id,
            MakerRecipe.organization_id == organization_id,
        )
    )
    recipe = recipe_result.scalar_one_or_none()
    total_fixed_cost = Decimal('0')
    if recipe is not None and recipe.batch_yield_qty > 0:
        batches = order.planned_qty / recipe.batch_yield_qty
        for cl in recipe.cost_lines:
            total_fixed_cost += cl.amount * batches
    return total_fixed_cost, recipe


def _snapshot_financial_result(
    order: ProductionOrder,
    recipe: MakerRecipe | None,
    unit_cost: Decimal,
    *,
    uncosted: bool = False,
) -> None:
    """financial result snapshot (reference_price − unit_cost).

    Stored per order so the catalog, order list, dashboard widget and cost
    history stay consistent even when the recipe changes later.

    A run that consumed an ingredient the ledger could not price states no
    result: its cost left that ingredient out, so the margin against it would
    be overstated by exactly what was left out - the recipe card withholds the
    same figure for the same reason. The cost itself is still kept.
    """
    if recipe is None:
        return
    order.unit_cost_snapshot = quantise(unit_cost, 4)
    order.reference_price_snapshot = recipe.reference_price
    if recipe.reference_price is not None and not uncosted:
        result_per_unit = quantise(recipe.reference_price - unit_cost)
        order.result_per_unit = result_per_unit
        order.result_per_batch = quantise(result_per_unit * recipe.batch_yield_qty)


@dataclass
class Consumption:
    """What a run took: the movements, what it cost, and the cost per unit.

    ``cost`` is what the cost ledger actually gave up — the run's material
    cost. ``unit_costs`` divides it per ingredient for the line snapshots;
    the total is kept whole so lines and order agree even when a cost does
    not divide evenly. An ingredient the ledger cannot price appears in
    neither, exactly as a missing rate did. ``shortfalls`` holds what a run
    recorded after the fact used beyond what the records held.
    """

    records: dict[UUID, list[stock_consumption.ConsumptionRecord]] = field(
        default_factory=dict
    )
    cost: Decimal = Decimal('0')
    unit_costs: dict[UUID, Decimal] = field(default_factory=dict)
    #: Per line of the flat list (by position), what the records lacked.
    shortfalls: dict[int, Decimal] = field(default_factory=dict)


async def _takeable_per_child(
    db: AsyncSession,
    organization_id: UUID,
    flat: list[tuple[UUID, Decimal, str]],
    location_id: UUID | None,
) -> dict[UUID, Decimal]:
    """How much of each ingredient the draw could take, at most its need.

    The plan the taking call itself follows (``plan_draw_async``), asked
    under the locks the run already holds, so what it names is what the draw
    can take: a short plan names what there is.
    """
    needs: dict[UUID, Decimal] = {}
    for child_id, child_qty, _unit in flat:
        needs[child_id] = needs.get(child_id, Decimal('0')) + child_qty
    takeable: dict[UUID, Decimal] = {}
    for child_id, need in needs.items():
        takes = await core_api.stock.plan_draw_async(
            db, organization_id, child_id, location_id, need, any_owner=True
        )
        takeable[child_id] = min(
            need, sum((take.consumed for take in takes), Decimal('0'))
        )
    return takeable


async def _consume_ingredients(
    db: AsyncSession,
    organization_id: UUID,
    order: ProductionOrder,
    flat: list[tuple[UUID, Decimal, str]],
    user: UserContextDTO,
    *,
    location_id: UUID | None = None,
    record_shortfall: bool = False,
) -> Consumption:
    """Take every exploded ingredient out of stock and off the books.

    *flat* arrives in stock units — see ``_explode_planned_consumption``.
    *location_id* is the scope the availability check judged the run under:
    the draw takes from that same set — the run's own shelf under
    PER_LOCATION, the whole organisation under GLOBAL.

    *record_shortfall* is a run that already happened: each ingredient takes
    what the records can give, at most its need, and the rest is the line's
    shortfall. The shortfall is valued at the ingredient's estimated cost —
    the goods were used, and a run of goods the records never held would
    otherwise cost nothing.
    """
    outcome = Consumption()
    consumed_per_child = outcome.records
    cost_sums: dict[UUID, Decimal] = {}
    qty_sums: dict[UUID, Decimal] = {}
    # From the top: every card the run touches — each ingredient and
    # the card its output is posted to — sorted, before the first draw is
    # planned. Locking each card when its own draw got there is the discipline
    # that ended in a few hundred deadlocks under concurrent runs. The output card is in
    # the set on purpose: a run that eats A to make B and one that eats B to
    # make A are exactly the shape that deadlocks without it.
    history_changes = {
        'reason': 'production_run',
        'production_order_id': str(order.id),
        'production_order_number': order.number or str(order.id),
    }
    await core_api.stock.lock_async(
        db,
        organization_id,
        keys=sorted(
            {(child_template_id, None) for child_template_id, _qty, _unit in flat}
            | {(order.output_template_id, None)}
        ),
    )
    takeable = (
        await _takeable_per_child(db, organization_id, flat, location_id)
        if record_shortfall
        else None
    )
    estimates = (
        await fetch_estimates_batch(db, organization_id, flat)
        if record_shortfall
        else {}
    )
    for index, (child_template_id, child_qty, _unit) in enumerate(flat):
        draw = child_qty
        if takeable is not None:
            draw = min(child_qty, takeable.get(child_template_id, Decimal('0')))
            takeable[child_template_id] = (
                takeable.get(child_template_id, Decimal('0')) - draw
            )
            if draw < child_qty:
                shortfall = child_qty - draw
                outcome.shortfalls[index] = shortfall
                rate = estimates.get(child_template_id, UnitCostEstimate()).unit_cost
                if rate is not None:
                    outcome.cost += rate * shortfall
                    cost_sums[child_template_id] = (
                        cost_sums.get(child_template_id, Decimal('0'))
                        + rate * shortfall
                    )
                    qty_sums[child_template_id] = (
                        qty_sums.get(child_template_id, Decimal('0')) + shortfall
                    )
        if draw <= 0:
            consumed_per_child.setdefault(child_template_id, [])
            continue
        child_template = await core_api.product_templates.get_async(
            db, organization_id, child_template_id
        )
        records = await stock_consumption.consume_across_locations(
            db,
            organization_id,
            child_template_id,
            draw,
            child_template=child_template,
            history_changes=history_changes,
            user_id=user.id,
            reference_id=order.id,
            location_id=location_id,
        )
        consumed_per_child.setdefault(child_template_id, []).extend(records)
        # And off the cost ledger. The draw above does not touch valuation,
        # and the record write it does is a bare quantity change — so a run
        # would raise a layer for what it made and lower none for what it
        # ate, counting the same stock twice. The picking path in recipes
        # has always posted its own; this is the same call.
        consumed_qty = sum((rec.consumed_qty for rec in records), Decimal('0'))
        cost = await core_api.valuation.record_delivery_async(
            db,
            organization_id,
            child_template_id,
            consumed_qty,
            reason=ItemAction.USED.value,
        )
        outcome.cost += cost or Decimal('0')
        if cost is not None:
            cost_sums[child_template_id] = (
                cost_sums.get(child_template_id, Decimal('0')) + cost
            )
            qty_sums[child_template_id] = (
                qty_sums.get(child_template_id, Decimal('0')) + consumed_qty
            )
    # Per unit, for the line snapshots. The total above is kept exact: an
    # ingredient whose cost does not divide evenly by its quantity would
    # otherwise make the lines and the order total disagree by the remainder.
    outcome.unit_costs = {
        child_id: quantise(cost_sums[child_id] / qty_sums[child_id], 4)
        for child_id in cost_sums
        if qty_sums.get(child_id)
    }
    return outcome


async def _receive_output(
    db: AsyncSession,
    organization_id: UUID,
    order: ProductionOrder,
    actual_qty: Decimal,
    unit_cost: Decimal,
    user: UserContextDTO,
) -> None:
    """Put the produced goods on the shelf (output = actual)."""
    template = await core_api.product_templates.get_async(
        db, organization_id, order.output_template_id
    )
    # The card's "purchase price per unit" and the fallback value for an
    # organization without cost layers — the same field the receipt path
    # fills when it opens a record. The layer posted below stays what the
    # stock is worth; this is what the run cost, kept where a person will
    # look for it. A zero means the run named no price at all (nothing it
    # consumed carried one), and the layer then reads unknown — the record
    # stays silent for the same reason. No currency question here: the cost
    # is what the organization's own cost ledger gave up for the run, so it
    # is already in the organization's money.
    #
    # The output's own anchor, named as a shelf: the run already holds the
    # card from the top with the ingredients (``_consume_ingredients``), and
    # this is the write AC names the lock for — the record is opened under it.
    await core_api.stock.lock_async(
        db,
        organization_id,
        keys=[(order.output_template_id, order.output_storage_location_id)],
    )
    # The output is filed where the product already lives — the category its
    # records carry — the same one answer the receipt follows. The run names
    # no source record, so the product answers; a product with no records
    # yet has nothing to inherit and stays unfiled.
    inherited_category_id = await core_api.items.inherited_category_async(
        db, organization_id, template_id=order.output_template_id
    )
    produced_item = await core_api.items.create_async(
        db,
        organization_id,
        ItemCreateDTO(
            name=template.name if template else 'Production output',
            template_id=order.output_template_id,
            category_id=inherited_category_id,
            location_id=order.output_storage_location_id,
            quantity=actual_qty,
            uom_id=template.uom_id if template else None,
            description=template.description if template else None,
            purchase_price=unit_cost if unit_cost > 0 else None,
        ),
        user=user,
        post_the_change=False,
    )
    order.produced_item_id = produced_item.id
    await core_api.stock.post_movement_async(
        db,
        organization_id,
        order.output_template_id,
        actual_qty,
        to_location_id=order.output_storage_location_id,
        reference_type='maker_production',
        reference_id=order.id,
        created_by=user.id,
    )

    # A run whose inputs carry no price still puts goods on the shelf, so it
    # still posts a layer -- `unit_cost=None` is how the core says "nobody
    # named a price", and it answers with this organization's own rate or,
    # failing that, a layer marked `unknown`. Skipping the call left the
    # quantity real and the value absent, which breaks the equality between
    # the shelf and the sum of the layers: the same hole the receipt path
    # closed, still open on the way out of production.
    await core_api.valuation.record_receipt_async(
        db,
        organization_id=organization_id,
        product_template_id=order.output_template_id,
        quantity=actual_qty,
        unit_cost=unit_cost if unit_cost > 0 else None,
    )


def _write_order_lines(
    db: AsyncSession,
    order: ProductionOrder,
    flat: list[tuple[UUID, Decimal, str]],
    consumption: Consumption,
) -> None:
    """One line per ingredient, at what that ingredient actually cost.

    The snapshot used to be the layer-average rate while the order total was
    the same average, so the two agreed. The total is now the real cost of the
    layers the run consumed, and a line that kept quoting the average would
    not add up to the order it belongs to.
    """
    for index, (child_template_id, child_qty, unit) in enumerate(flat):
        rate = consumption.unit_costs.get(child_template_id)
        records = consumption.records.get(child_template_id, [])
        dominant_loc = (
            max(records, key=lambda r: r.consumed_qty).storage_location_id
            if records
            else None
        )
        db.add(
            ProductionOrderLine(
                production_order_id=order.id,
                child_template_id=child_template_id,
                consumed_qty=child_qty,
                unit=unit,
                source_storage_location_id=dominant_loc,
                unit_cost_snapshot=rate,
                cost_source='fifo' if rate is not None else 'none',
                shortfall_qty=consumption.shortfalls.get(index),
            )
        )


async def complete_production(
    db: AsyncSession,
    organization_id: UUID,
    order_id: UUID,
    user: UserContextDTO,
    *,
    actual_qty: Decimal | None = None,
    record_shortfall: bool = False,
) -> ProductionOrder:
    """Execute the full atomic production pipeline (see module docstring).

    Semantics: full planned consumption, output = ``actual_qty``.

    - ``actual_qty`` defaults to ``planned_qty`` when omitted (backward compat).
    - ``actual_qty`` must be > 0; zero outputs = cancel + write-off.
    - ``actual > planned`` gated by ``settings.allow_overproduction``.
    - Fixed cost lines on the recipe are included in ``total_cost``.
    - ``unit_cost = total_cost / actual_qty``.
    - ``record_shortfall``: the run already happened, so an ingredient the
      records hold too little of is taken as far as they go and the rest is
      recorded on its line (``record_made``) instead of refusing the run.
    """
    order = await _lock_draft_order(db, organization_id, order_id)
    # The period guard every stock-writing path asks. The run already could
    # not slip through — the item bridge under the pipeline trips the same
    # guard mid-flight — but a refusal after the explosion and the
    # availability question is the guard answering late: asked here, first,
    # the closed month answers before any work, like a document.
    await core_api.periods.check_not_closed_async(
        db, organization_id, order.production_date or date.today()
    )
    actual_qty = await _resolve_actual_qty(db, organization_id, order, actual_qty)
    overproduced = actual_qty > order.planned_qty
    scrap_qty = order.planned_qty - actual_qty

    flat = await _explode_planned_consumption(db, organization_id, order)
    # One answer for the two doors: the availability check and the draw
    # read the same resolved scope, so a run is judged on the stock it may
    # actually take — PER_LOCATION checks and eats the run's own output
    # shelf, GLOBAL checks and eats the whole organisation. Two sets here
    # meant a run passing on its shelf while eating the far corner.
    from .availability_service import resolve_check_location

    check_location_id = await resolve_check_location(
        db,
        organization_id,
        context_location_id=order.output_storage_location_id,
    )
    await _assert_stock_is_available(
        db,
        organization_id,
        order,
        check_location_id,
        record_shortfall=record_shortfall,
    )

    # Consume first, then cost. The material cost is what the cost ledger
    # actually gave up for these ingredients, which is only known once the
    # layers have been drained — and it is not the average of the layers
    # standing beforehand, which is what this used to charge. A manufacturing
    # order in Odoo and ERPNext values its output at the real cost of the
    # components it consumed, and after the outgoing layer is posted at its
    # FIFO cost the two figures stop agreeing. An ingredient the ledger
    # cannot price contributes nothing, exactly as a missing rate did.
    consumption = await _consume_ingredients(
        db,
        organization_id,
        order,
        flat,
        user,
        location_id=check_location_id,
        record_shortfall=record_shortfall,
    )
    total_material_cost = consumption.cost
    total_fixed_cost, recipe = await _fixed_cost_and_recipe(db, organization_id, order)

    total_cost = total_material_cost + total_fixed_cost
    unit_cost = (
        total_cost / actual_qty if actual_qty > 0 and total_cost > 0 else Decimal('0')
    )
    uncosted = any(
        child_template_id not in consumption.unit_costs
        for child_template_id, _qty, _unit in flat
    )
    _snapshot_financial_result(order, recipe, unit_cost, uncosted=uncosted)

    await _receive_output(db, organization_id, order, actual_qty, unit_cost, user)
    _write_order_lines(db, order, flat, consumption)

    order.status = 'COMPLETED'
    order.total_cost = total_cost
    order.actual_qty = actual_qty
    order.overproduced = overproduced
    order.scrap_qty = scrap_qty
    order.completed_at = datetime.now(tz=UTC)
    order.completed_by = user.id
    # The date is optional at planning and nobody plans it; at closing it is
    # known to the day — an empty "PRODUCTION DATE —" on a finished run
    # served nobody.
    if order.production_date is None:
        order.production_date = order.completed_at.date()

    # The run is the event; the four QUANTITY_CHANGE rows the item bridge
    # writes below are its consequences. Without this entry the organization
    # log held a closed run that never appeared to have happened — and the
    # answer to "why did the wax go down" lived only inside the module, on
    # the order screen you had to know to open.
    output = await core_api.product_templates.get_async(
        db, organization_id, order.output_template_id
    )
    await core_api.audit_log.log_action_async(
        db,
        organization_id=organization_id,
        user_id=user.id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.MAKER_PRODUCTION_ORDER,
        target_id=order.id,
        snapshot={
            'name': order.number,
            'old_status': 'DRAFT',
            'new_status': 'COMPLETED',
            'output': output.name if output else None,
            'quantity': _stored_qty(actual_qty),
            'total_cost': quantise(total_cost, 2),
        },
    )

    await db.flush()
    logger.info(
        'Production order %s completed (output=%s, planned=%s, actual=%s, cost=%s)',
        order.id,
        order.output_template_id,
        order.planned_qty,
        actual_qty,
        total_cost,
    )
    return order


async def record_made(
    db: AsyncSession,
    organization_id: UUID,
    data: ProductionOrderCreate,
    user: UserContextDTO,
) -> ProductionOrder:
    """Record a run that has already happened: one step, create and complete.

    "I made 20 kg" used to be a draft first and a completion second, and the
    completion refused a run whose ingredients the records did not hold —
    for goods that were already made. Here the order is opened and closed in
    the same transaction. The shortage strategy is not asked: it decides
    whether to plan a run over stock, and this one is not a plan. An
    ingredient short in the records is taken as far as they go and the rest
    is recorded on its line, which puts the ingredient up for a count.
    """
    order = await create_order(
        db,
        organization_id,
        data.model_copy(update={'confirm_shortage': True}),
        user,
    )
    return await complete_production(
        db, organization_id, order.id, user, record_shortfall=True
    )


async def preview_production(
    db: AsyncSession,
    organization_id: UUID,
    data: ProductionOrderCreate,
) -> ProductionPreviewResponse:
    """What a run would take, what is short and what it would cost — read-only.

    The shortages are judged where completion judges them: the scope the
    run's own output location resolves to. The cost per unit adds the
    recipe's fixed costs the way completion does (``_fixed_cost_and_recipe``),
    so the figure the person saves on is the figure the run records.
    """
    from . import cost_breakdown
    from .availability_service import compute_availability, resolve_check_location

    breakdown = await cost_breakdown.compute_breakdown(
        db,
        organization_id,
        data.output_template_id,
        data.planned_qty,
        recipe_id=data.recipe_id,
    )
    preview = ProductionPreviewResponse(**breakdown.model_dump())
    if breakdown.recipe_id is None:
        return preview
    recipe = await bom_service.resolve_recipe(db, organization_id, breakdown.recipe_id)
    preview.batch_yield_qty = recipe.batch_yield_qty
    preview.reference_price = recipe.reference_price
    if not recipe.batch_yield_qty:
        return preview
    batches = data.planned_qty / recipe.batch_yield_qty
    check_location_id = await resolve_check_location(
        db, organization_id, context_location_id=data.output_location_id
    )
    availability = await compute_availability(
        db, organization_id, recipe.id, batches=batches, location_id=check_location_id
    )
    preview.ingredients = [
        IngredientAvailabilityItem.model_validate(ingredient, from_attributes=True)
        for ingredient in availability.ingredients
    ]
    preview.has_shortage = availability.has_shortage or availability.has_unknown
    preview.fixed_cost = quantise(
        sum((line.amount for line in recipe.cost_lines), Decimal('0')) * batches
    )
    total = breakdown.total_cost + preview.fixed_cost
    if total > 0:
        preview.unit_cost = quantise(total / data.planned_qty, 4)
        if recipe.reference_price is not None:
            preview.result_per_unit = quantise(
                recipe.reference_price - total / data.planned_qty
            )
    return preview


async def add_shortages_to_shopping_list(
    db: AsyncSession,
    organization_id: UUID,
    data: ProductionOrderCreate,
    user: UserContextDTO,
    lang: Language,
) -> ShortageShoppingListResponse:
    """Put what a planned run lacks on the shopping list being filled.

    Short by the same verdict completion refuses with, and as much as is
    missing, in each ingredient's stock unit — the unit it is bought and
    received in. An ingredient already on that list is not added twice, and
    one whose measure cannot be compared with its stock has no quantity to
    buy and is left out. Nothing short, nothing touched.
    """
    from app.modules.shopping_lists.shopping_lists_api import shopping_lists_api

    from .availability_service import (
        _get_available_stock_batch,
        compute_shortage_list,
        resolve_check_location,
    )

    recipe = (
        await bom_service.resolve_recipe(db, organization_id, data.recipe_id)
        if data.recipe_id is not None
        else await bom_service.find_default_recipe(
            db, organization_id, data.output_template_id
        )
    )
    if recipe is None:
        raise ServiceRejectionError('production_no_recipe')
    check_location_id = await resolve_check_location(
        db, organization_id, context_location_id=data.output_location_id
    )
    shortages = await compute_shortage_list(
        db, organization_id, recipe.id, data.planned_qty, location_id=check_location_id
    )
    short_ids = [
        item.child_template_id
        for item in shortages
        if item.shortage is not None and item.shortage > 0
    ]
    if not short_ids:
        return ShortageShoppingListResponse()

    needs: dict[UUID, Decimal] = {}
    for child_id, child_qty, _unit in await bom_service.explode_in_stock_units(
        db,
        organization_id,
        data.output_template_id,
        data.planned_qty,
        recipe_id=recipe.id,
    ):
        needs[child_id] = needs.get(child_id, Decimal('0')) + child_qty
    stocks = await _get_available_stock_batch(
        db, organization_id, short_ids, location_id=check_location_id
    )
    templates = await core_api.product_templates.get_many_async(
        db, organization_id, short_ids
    )
    shopping_list = await shopping_lists_api.active_list_async(
        db, organization_id, user.id, lang
    )
    listed = {
        item.template_id
        for item in await shopping_lists_api.get_list_items_async(
            db, shopping_list.id, organization_id
        )
    }
    to_buy: list[ShoppingListItemCreateDTO] = []
    for child_id in short_ids:
        missing = needs.get(child_id, Decimal('0')) - stocks.get(child_id, Decimal('0'))
        template = templates.get(child_id)
        if missing <= 0 or template is None or child_id in listed:
            continue
        to_buy.append(
            ShoppingListItemCreateDTO(
                name=template.name,
                # Up, not to the nearest: buying a gram less than the run
                # needs leaves it short. No unit's step applies to a
                # shortfall summed across recipes, so the store's own step.
                quantity=core_api.uoms.round_up(missing, None),
                uom_id=template.uom_id,
                template_id=child_id,
                source='production',
            )
        )
    added = (
        await shopping_lists_api.add_items_async(
            db, shopping_list.id, to_buy, organization_id
        )
        if to_buy
        else []
    )
    return ShortageShoppingListResponse(
        shopping_list_id=shopping_list.id,
        list_name=shopping_list.name,
        added_count=len(added),
    )


async def cancel_order(
    db: AsyncSession,
    organization_id: UUID,
    order_id: UUID,
    user: UserContextDTO,
    *,
    reason: str | None = None,
) -> ProductionOrder:
    """Cancel a DRAFT order. COMPLETED orders are immutable.

    The optional ``reason`` is stored inline (``cancel_reason``) and mirrored
    to the global audit log so the trail survives even if the order row is
    later deleted.
    """
    order = await get_order(db, organization_id, order_id)
    if order is None:
        raise EntityNotFoundError(
            'production_order', f'Production order {order_id} not found'
        )
    # Re-read under the row lock a completion takes, so a cancel that arrives
    # mid-completion waits for it and sees the run is no longer a draft.
    await db.refresh(order, with_for_update=True)
    if order.status != 'DRAFT':
        raise ServiceRejectionError('production_cancel_not_draft', status=order.status)
    order.status = 'CANCELLED'
    order.completed_at = datetime.now(tz=UTC)
    order.completed_by = user.id
    order.cancel_reason = reason
    await core_api.audit_log.log_action_async(
        db,
        organization_id=organization_id,
        user_id=user.id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.MAKER_PRODUCTION_ORDER,
        target_id=order.id,
        snapshot={
            'name': order.number,
            'old_status': 'DRAFT',
            'new_status': 'CANCELLED',
        },
        reason=reason,
    )
    await db.flush()
    return order


async def update_order(
    db: AsyncSession,
    organization_id: UUID,
    order_id: UUID,
    data: ProductionOrderUpdate,
    user: UserContextDTO,
) -> ProductionOrder:
    """Update editable fields of a DRAFT order.

    Only DRAFT orders are editable. ``planned_qty``, ``production_date``
    and ``notes`` may be patched; everything else is immutable.
    """
    order = await get_order(db, organization_id, order_id)
    if order is None:
        raise EntityNotFoundError(
            'production_order', f'Production order {order_id} not found'
        )
    # The DRAFT check is a read-modify-write: a completion in flight holds
    # this row, so read it again under the lock before trusting the status.
    # An edit arriving while another is saved waits the same way, and
    # journals what it changes from what that one left.
    await db.refresh(order, with_for_update=True)
    if order.status != 'DRAFT':
        raise ServiceRejectionError('production_update_not_draft', status=order.status)
    before = _plan_shape(order)
    planned_qty_changed = (
        data.planned_qty is not None and order.planned_qty != data.planned_qty
    )
    if data.planned_qty is not None:
        order.planned_qty = data.planned_qty
    if data.production_date is not None:
        order.production_date = data.production_date
    if data.notes is not None:
        order.notes = data.notes
    # The flag answers "was this run ever satisfiable?" — a changed planned
    # quantity changes the answer, so it is recomputed with the new one.
    if planned_qty_changed and order.recipe_id is not None:
        from .availability_service import compute_shortage_list, resolve_check_location

        check_location_id = await resolve_check_location(
            db,
            organization_id,
            context_location_id=order.output_storage_location_id,
        )
        shortages = await compute_shortage_list(
            db,
            organization_id,
            order.recipe_id,
            order.planned_qty,
            location_id=check_location_id,
        )
        order.short_at_create = bool(shortages)
    await db.flush()
    # A planned run that changed size is the question asked of the log when
    # the shelf does not hold what the plan said; a resave writes nothing.
    after = _plan_shape(order)
    moved = [key for key in before if before[key] != after[key]]
    if moved:
        await core_api.audit_log.log_action_async(
            db,
            organization_id=organization_id,
            user_id=user.id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.MAKER_PRODUCTION_ORDER,
            target_id=order.id,
            snapshot={
                'name': order.number,
                'before': {key: before[key] for key in moved},
                'after': {key: after[key] for key in moved},
            },
        )
    return order


async def duplicate_order(
    db: AsyncSession,
    organization_id: UUID,
    order_id: UUID,
    user: UserContextDTO,
) -> ProductionOrder:
    """Create a fresh DRAFT order seeded from an existing one.

    Copies the immutable planning fields (template, recipe, qty, storage,
    date, notes). The duplicate is always DRAFT — no lines, no produced
    item, no cost snapshot (those are completion-time artefacts). ``notes``
    is prefixed with ``[duplicate]`` to make the copy traceable.
    """
    source = await get_order(db, organization_id, order_id)
    if source is None:
        raise EntityNotFoundError(
            'production_order', f'Production order {order_id} not found'
        )

    dup_notes = f'[duplicate] {source.notes}' if source.notes else '[duplicate]'
    # The duplicate is measured on its own against today's stock — the fact
    # travels with the order it belongs to, not with its source.
    short_at_create = False
    if source.recipe_id is not None:
        from .availability_service import compute_shortage_list, resolve_check_location

        check_location_id = await resolve_check_location(
            db,
            organization_id,
            context_location_id=source.output_storage_location_id,
        )
        shortages = await compute_shortage_list(
            db,
            organization_id,
            source.recipe_id,
            source.planned_qty,
            location_id=check_location_id,
        )
        short_at_create = bool(shortages)
    dup = ProductionOrder(
        organization_id=organization_id,
        number=await _next_order_number(db, organization_id),
        output_template_id=source.output_template_id,
        recipe_id=source.recipe_id,
        planned_qty=source.planned_qty,
        output_storage_location_id=source.output_storage_location_id,
        production_date=source.production_date,
        notes=dup_notes,
        created_by=user.id,
        status='DRAFT',
        short_at_create=short_at_create,
    )
    db.add(dup)
    await db.flush()
    await _journal_opened(db, dup, user, copied_from=source.number)
    return dup
