"""Public Cross-Module API for the maker module.

Other modules (e.g. recipes → "make this recipe") can call these methods
to query BOMs and cost without importing maker internals. All methods
work when the maker module is disabled (they raise ``LookupError``/empty
data) so consumer modules don't need to guard every call.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO, WorkItemDTO, WorkItemQueryDTO
from app.core.public_api import core_api

from . import bom_service, cost_breakdown, cost_rollup, production_service
from ._schemas_breakdown import CostBreakdownResponse
from .models import BoMLine, ProductionOrder, ProductionOrderLine


class MakerAPI:
    """Single public entry point for cross-module consumption of maker data.

    Mirrors the ``approvals_api`` / ``warehouse_api`` / ``purchase_orders_api``
    pattern (AGENTS.md §Cross-Module API): one public API per module, no
    internal model/service imports allowed in consumers.
    """

    async def list_bom_lines_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        template_id: UUID,
    ) -> list[BoMLine]:
        """Return the BOM lines for ``template_id`` (ingredients only)."""
        return await bom_service.list_lines(db, organization_id, template_id)

    async def list_template_ids_with_bom_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
    ) -> list[UUID]:
        """Product templates in the organization that have at least one BOM line.

        The product list uses it to offer "has a formula" as a filter rather
        than only as a badge. Core cannot answer this — a formula is a maker
        concept — and the list is virtualised, so the answer has to arrive as a
        set of ids rather than row by row.
        """
        parents = await bom_service.list_parents(db, organization_id)
        return [template_id for template_id, _count in parents]

    async def explode_bom_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        template_id: UUID,
        qty: Decimal,
    ) -> list[tuple[UUID, Decimal, str]]:
        """Flat-list of (child_template_id, effective_qty, unit) for ``qty`` units."""
        return await bom_service.explode(db, organization_id, template_id, qty)

    async def compute_total_cost_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        template_id: UUID,
        qty: Decimal,
    ) -> Decimal:
        """Sum of layer-average rate × effective_qty across the multi-level BOM.

        Stock value is FIFO; the rate is the average cost of the layers
        still on hand (the ``avco`` label in source fields is historical).
        """
        return await cost_rollup.compute_total_cost(
            db, organization_id, template_id, qty
        )

    async def compute_unit_cost_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        template_id: UUID,
        planned_qty: Decimal,
    ) -> Decimal:
        """Cost per produced unit (zero when no rateable inputs exist)."""
        return await cost_rollup.compute_unit_cost(
            db, organization_id, template_id, planned_qty
        )

    async def get_breakdown_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        template_id: UUID,
        qty: Decimal,
    ) -> CostBreakdownResponse:
        """Per-ingredient cost breakdown (read-only, no stock mutation)."""
        return await cost_breakdown.compute_breakdown(
            db, organization_id, template_id, qty
        )

    async def list_work_items_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        query: WorkItemQueryDTO,
    ) -> tuple[list[WorkItemDTO], int]:
        """Draft production runs planned for ``query.date_to`` or earlier.

        To do's provider for this module. A run with no planned day is not
        work for any particular day and stays out. Oldest day first;
        ``subject`` is the product to make and ``count`` the quantity
        planned. When ``query.done_since`` is set, the runs recorded since
        then come back as ``done`` with the quantity made.

        After them, the counts the runs recorded after the fact asked for:
        see ``_shortfall_counts``.
        """
        from sqlalchemy import func, or_, select

        planned = and_(
            ProductionOrder.status == 'DRAFT',
            ProductionOrder.production_date.is_not(None),
            ProductionOrder.production_date <= query.date_to,
        )
        wanted = planned
        if query.done_since is not None:
            wanted = or_(
                planned,
                and_(
                    ProductionOrder.status == 'COMPLETED',
                    ProductionOrder.completed_at >= query.done_since,
                ),
            )
        due = (ProductionOrder.organization_id == organization_id, wanted)
        total = (
            await db.scalar(
                select(func.count()).select_from(ProductionOrder).where(*due)
            )
        ) or 0
        orders = (
            (
                await db.execute(
                    select(ProductionOrder)
                    .where(*due)
                    .order_by(ProductionOrder.production_date, ProductionOrder.number)
                    .limit(query.limit)
                )
            )
            .scalars()
            .all()
        )
        # A quantity of goods is meaningless without its measure.
        symbols = (
            {
                uom.id: uom.symbol
                for uom in await core_api.uoms.list_for_org_async(db, organization_id)
            }
            if orders
            else {}
        )
        runs = [
            WorkItemDTO(
                kind='produce',
                source_kind='production_order',
                source_id=order.id,
                state='done' if order.status == 'COMPLETED' else 'todo',
                due_date=order.production_date,
                number=order.number,
                subject=order.output_template.name,
                count=order.actual_qty
                if order.status == 'COMPLETED' and order.actual_qty is not None
                else order.planned_qty,
                unit=(
                    symbols.get(order.output_template.uom_id)
                    if order.output_template.uom_id
                    else None
                ),
                next_action=None if order.status == 'COMPLETED' else 'produce',
                done_at=order.completed_at if order.status == 'COMPLETED' else None,
            )
            for order in orders
        ]
        counts = await _shortfall_counts(db, organization_id, query)
        return (runs + counts)[: query.limit], total + len(counts)

    async def complete_production_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        order_id: UUID,
        user: UserContextDTO,
        *,
        actual_qty: Decimal | None = None,
    ) -> ProductionOrder:
        """Execute a DRAFT production order (consume → produce → valuation).

        ``actual_qty``: real output quantity. Defaults to
        ``planned_qty`` when ``None``.
        """
        return await production_service.complete_production(
            db, organization_id, order_id, user, actual_qty=actual_qty
        )


async def _shortfall_counts(
    db: AsyncSession,
    organization_id: UUID,
    query: WorkItemQueryDTO,
) -> list[WorkItemDTO]:
    """A count for each ingredient a run recorded after the fact found short.

    The run used goods the records did not hold, so the records are wrong
    where the ingredient is kept: that location is due a count — the
    location the line drew from, or the run's own output location when it
    drew nothing. The task stands until a count of that location closes after
    the run (then it is ``done``, returned only when asked for), and only
    while the stock takes module is on: without it there is nowhere to count.
    ``subject`` is the ingredient, ``number`` the run, ``count`` the shortfall.
    """
    from sqlalchemy import select

    from app.core.public_api import core_api

    if not await core_api.organizations.is_module_enabled_async(
        db, organization_id, 'stock_takes'
    ):
        return []
    from app.modules.stock_takes.stock_takes_api import stock_takes_api

    rows = (
        await db.execute(
            select(ProductionOrderLine, ProductionOrder)
            .join(
                ProductionOrder,
                ProductionOrderLine.production_order_id == ProductionOrder.id,
            )
            .where(
                ProductionOrder.organization_id == organization_id,
                ProductionOrder.status == 'COMPLETED',
                ProductionOrderLine.shortfall_qty > 0,
            )
            .order_by(ProductionOrder.completed_at)
        )
    ).all()
    if not rows:
        return []
    location_ids = {
        line.source_storage_location_id or order.output_storage_location_id
        for line, order in rows
    }
    storages = {
        storage.id: storage
        for location_id in location_ids
        if (
            storage := await core_api.locations.get_async(
                db, organization_id, location_id
            )
        )
        is not None
    }
    counted = await stock_takes_api.last_counted_async(
        db, organization_id, list(storages.values())
    )
    templates = await core_api.product_templates.get_many_async(
        db, organization_id, list({line.child_template_id for line, _ in rows})
    )
    tasks: list[WorkItemDTO] = []
    for line, order in rows:
        location_id = (
            line.source_storage_location_id or order.output_storage_location_id
        )
        counted_at = counted.get(location_id)
        recounted = (
            counted_at is not None
            and order.completed_at is not None
            and counted_at >= order.completed_at
        )
        if recounted and (
            query.done_since is None
            or counted_at is None
            or counted_at < query.done_since
        ):
            continue
        if (
            not recounted
            and order.production_date
            and order.production_date > query.date_to
        ):
            continue
        template = templates.get(line.child_template_id)
        storage = storages.get(location_id)
        tasks.append(
            WorkItemDTO(
                kind='count',
                source_kind='production_shortfall',
                source_id=line.id,
                state='done' if recounted else 'todo',
                due_date=order.production_date,
                number=order.number,
                subject=template.name if template else None,
                place=storage.name if storage else None,
                count=line.shortfall_qty,
                next_action=None if recounted else 'count',
                action_href=None
                if recounted
                else f'/inventory/stock-takes/count?location={location_id}',
            )
        )
    return tasks


maker_api = MakerAPI()
