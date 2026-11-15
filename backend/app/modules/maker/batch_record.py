"""The batch record of a completed run: what was made, of what, by whom.

One page a producer keeps or hands an inspector: the formula and its
variant, the planned and the actual quantity, each ingredient with the
batches and quantities taken, the costs, who planned and who closed the run
and when, its notes and its files. The batches come from the movements the
run wrote — each names the batch it took — so the record says what the
shelves gave, not what the formula asked.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import StockMoveDTO
from app.core.exceptions import EntityNotFoundError, ServiceRejectionError
from app.core.money import quantise
from app.core.public_api import core_api

from . import output_batch, production_attachments, production_service
from ._schemas_batches import (
    BatchRecordBatch,
    BatchRecordIngredient,
    BatchRecordRead,
)
from .models import MakerRecipe, ProductionOrder

#: Moves read per page while gathering a run's draw.
_PAGE = 200


async def _all_moves(
    db: AsyncSession, organization_id: UUID, order_id: UUID
) -> list[StockMoveDTO]:
    moves: list[StockMoveDTO] = []
    offset = 0
    while True:
        page = await core_api.stock_moves.list_by_reference_async(
            db,
            organization_id,
            'maker_production',
            order_id,
            limit=_PAGE,
            offset=offset,
        )
        moves.extend(page)
        if len(page) < _PAGE:
            return moves
        offset += _PAGE


def _taken_by_batch(
    moves: list[StockMoveDTO], output_template_id: UUID
) -> dict[UUID, dict[UUID | None, Decimal]]:
    """Ingredient -> batch -> quantity the run took off the shelves.

    The way in only: a move off a shelf into the run. A run taken back
    writes the way back too, and those return to a shelf.
    """
    taken: dict[UUID, dict[UUID | None, Decimal]] = {}
    for move in moves:
        if (
            move.product_template_id == output_template_id
            or move.from_location_id is None
            or move.to_location_id is not None
        ):
            continue
        per_lot = taken.setdefault(move.product_template_id, {})
        per_lot[move.lot_id] = per_lot.get(move.lot_id, Decimal('0')) + move.quantity
    return taken


async def build_batch_record(
    db: AsyncSession, organization_id: UUID, order_id: UUID
) -> BatchRecordRead:
    """The record of one run; refused for a run that never completed."""
    order = await db.scalar(
        select(ProductionOrder).where(
            ProductionOrder.organization_id == organization_id,
            ProductionOrder.id == order_id,
        )
    )
    if order is None:
        raise EntityNotFoundError('production_order', str(order_id))
    if order.completed_at is None:
        raise ServiceRejectionError('production_record_not_completed')

    lines = await production_service.list_lines(db, organization_id, order_id)
    template_ids = list({line.child_template_id for line in lines})
    templates = await core_api.product_templates.get_many_async(
        db, organization_id, [*template_ids, order.output_template_id]
    )
    lots = {}
    for template_id in template_ids:
        for lot in await core_api.stock.list_lots_async(
            db, organization_id, template_id
        ):
            lots[lot.id] = lot
    taken = _taken_by_batch(
        await _all_moves(db, organization_id, order_id), order.output_template_id
    )

    ingredients: list[BatchRecordIngredient] = []
    material = Decimal('0')
    for line in lines:
        cost = (
            quantise(line.consumed_qty * line.unit_cost_snapshot, 2)
            if line.unit_cost_snapshot is not None
            else None
        )
        material += cost or Decimal('0')
        template = templates.get(line.child_template_id)
        ingredients.append(
            BatchRecordIngredient(
                template_id=line.child_template_id,
                template_name=template.name if template else None,
                unit=line.unit,
                consumed_qty=line.consumed_qty,
                shortfall_qty=line.shortfall_qty,
                unit_cost=line.unit_cost_snapshot,
                cost=cost,
                batches=[
                    BatchRecordBatch(
                        lot_id=lot_id,
                        lot_name=lots[lot_id].name if lot_id in lots else None,
                        expiry_date=(
                            (lots[lot_id].expiry_date or lots[lot_id].use_by_date)
                            if lot_id in lots
                            else None
                        ),
                        quantity=qty,
                    )
                    for lot_id, qty in taken.pop(line.child_template_id, {}).items()
                ],
            )
        )

    # Every batch the output was filed under, the run's own first: the record
    # names all of them, and speaks of the first where it has room for one.
    output_lots = await output_batch.lots_of_run_async(db, organization_id, order)
    output_lot = output_lots[0] if output_lots else None
    recipe_name = (
        await db.scalar(
            select(MakerRecipe.name).where(
                MakerRecipe.organization_id == organization_id,
                MakerRecipe.id == order.recipe_id,
            )
        )
        if order.recipe_id is not None
        else None
    )
    people = {
        user.id: user.full_name or user.email
        for user in await core_api.users.get_by_ids_async(
            db,
            organization_id,
            [uid for uid in (order.created_by, order.completed_by) if uid],
        )
    }
    location = await core_api.locations.get_async(
        db, organization_id, order.output_storage_location_id
    )
    output = templates.get(order.output_template_id)
    uom_symbol = None
    if output is not None and output.uom_id is not None:
        symbols = {
            uom.id: uom.symbol
            for uom in await core_api.uoms.list_for_org_async(db, organization_id)
        }
        uom_symbol = symbols.get(output.uom_id)
    attachments = await production_attachments.list_attachments(
        db, organization_id, order_id
    )
    return BatchRecordRead(
        order_id=order.id,
        number=order.number,
        status=order.status,
        output_template_name=output.name if output else None,
        recipe_name=recipe_name,
        output_uom_symbol=uom_symbol,
        planned_qty=order.planned_qty,
        actual_qty=order.actual_qty,
        scrap_qty=order.scrap_qty,
        output_lot_name=order.output_lot_name,
        output_lot_status=output_lot.status if output_lot else None,
        output_batches=output_batch.run_batch_reads(output_lots),
        production_date=order.production_date,
        best_before=(
            (output_lot.expiry_date or output_lot.use_by_date) if output_lot else None
        ),
        output_location_name=location.name if location else None,
        ingredients=ingredients,
        material_cost=material if lines else None,
        total_cost=order.total_cost,
        estimated_total_cost=order.estimated_total_cost,
        unit_cost=(
            quantise(order.total_cost / order.actual_qty, 4)
            if order.total_cost is not None and order.actual_qty
            else None
        ),
        created_by_name=people.get(order.created_by) if order.created_by else None,
        created_at=order.created_at,
        completed_by_name=(
            people.get(order.completed_by) if order.completed_by else None
        ),
        completed_at=order.completed_at,
        notes=order.notes,
        attachments=[
            production_attachments.to_read(organization_id, row) for row in attachments
        ],
    )
