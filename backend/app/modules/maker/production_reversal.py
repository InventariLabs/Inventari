"""Taking a completed production run back.

A completed run stays as it was — its lines, its cost and its number are the
record of what happened — and the way back from a mistake is the entry beside
it that undoes the stock, the same way a receipt or an issue is undone by the
correction the warehouse writes for it. A run typed as 20 instead of 2 took
ten times its ingredients out of stock; by hand, putting them back is one
correction per ingredient and shelf by someone who knows where each came from.

What the run took is read back from the movements it wrote: one per shelf,
batch, owner and date it drew on, so each ingredient returns to the record it
left, with its batch and its expiry. The output comes off the record the run
opened for it. Every movement of the reversal names the run, so the run's own
moves list and the moves register show the way out and the way back together.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    ItemCreateDTO,
    RecordPostDTO,
    StockMoveDTO,
    UserContextDTO,
)
from app.core.exceptions import EntityNotFoundError, ServiceRejectionError
from app.core.public_api import core_api

from .models import ProductionOrder, ProductionOrderLine

_REFERENCE_TYPE = 'maker_production'


async def reverse_production(
    db: AsyncSession,
    organization_id: UUID,
    order_id: UUID,
    user: UserContextDTO,
) -> ProductionOrder:
    """Put back what a completed run consumed and take off what it made.

    Refused for a run that is not completed, and for a run whose output has
    since left its shelf: the goods it made are no longer there to take back,
    and taking other stock in their place would hide the use. The rule is the
    warehouse's own for undoing a document — a later movement off the shelf
    refuses the undo even when another receipt has replenished it.

    Nothing commits here; the request owns the transaction, so a refusal
    halfway leaves the run and the stock as they were.
    """
    order = (
        await db.execute(
            select(ProductionOrder)
            .where(
                ProductionOrder.organization_id == organization_id,
                ProductionOrder.id == order_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if order is None:
        raise EntityNotFoundError(
            'production_order', f'Production order {order_id} not found'
        )
    if order.status != 'COMPLETED':
        raise ServiceRejectionError(
            'production_reverse_not_completed', status=order.status
        )
    # The reversal posts today, so today's period is the one that has to be
    # open — the same guard every stock-writing path asks first.
    await core_api.periods.check_not_closed_async(
        db,
        organization_id,
        await core_api.organizations.today_async(db, organization_id),
    )

    moves = await core_api.stock_moves.list_by_reference_async(
        db, organization_id, _REFERENCE_TYPE, order.id, limit=10_000
    )
    # Every card the reversal writes, sorted, before the first write — the
    # discipline the run itself follows on the way in.
    await core_api.stock.lock_async(
        db,
        organization_id,
        keys=sorted(
            {(move.product_template_id, None) for move in moves}
            | {(order.output_template_id, None)}
        ),
    )
    history = {
        'reason': f'Production run {order.number or order.id} taken back',
        'production_order_id': str(order.id),
    }
    await _take_the_output_off(db, organization_id, order, user, history)
    rates = await _ingredient_rates(db, order.id)
    for move in moves:
        if move.from_location_id is not None and move.to_location_id is None:
            await _put_the_ingredient_back(
                db, organization_id, order, move, user, history, rates
            )

    order.status = 'REVERSED'
    await core_api.audit_log.log_action_async(
        db,
        organization_id=organization_id,
        user_id=user.id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.MAKER_PRODUCTION_ORDER,
        target_id=order.id,
        snapshot={
            'name': order.number,
            'old_status': 'COMPLETED',
            'new_status': 'REVERSED',
        },
    )
    await db.flush()
    return order


async def _take_the_output_off(
    db: AsyncSession,
    organization_id: UUID,
    order: ProductionOrder,
    user: UserContextDTO,
    history: dict[str, str],
) -> None:
    """Take the run's output off the record the run opened for it."""
    made = order.actual_qty or Decimal('0')
    produced = (
        await core_api.items.get_for_update_async(
            db, organization_id, order.produced_item_id
        )
        if order.produced_item_id is not None
        else None
    )
    if (
        produced is None
        or (produced.quantity or Decimal('0')) < made
        or produced.location_id != order.output_storage_location_id
        or await core_api.stock_moves.any_departure_async(
            db,
            organization_id,
            product_template_id=order.output_template_id,
            from_location_id=order.output_storage_location_id,
            lot_id=None,
            owner_id=None,
            since=order.completed_at or order.created_at,
            excluded_reference_ids=[order.id],
        )
    ):
        raise ServiceRejectionError('production_reverse_output_used')
    await core_api.stock.post_movement_async(
        db,
        organization_id,
        order.output_template_id,
        made,
        from_location_id=order.output_storage_location_id,
        reference_type=_REFERENCE_TYPE,
        reference_id=order.id,
        created_by=user.id,
        records=[
            RecordPostDTO(
                item_id=produced.id,
                new_quantity=(produced.quantity or Decimal('0')) - made,
                history=history,
            )
        ],
    )
    await core_api.valuation.record_delivery_async(
        db,
        organization_id,
        order.output_template_id,
        made,
        item_id=produced.id,
    )


async def _ingredient_rates(
    db: AsyncSession, order_id: UUID
) -> dict[UUID, Decimal | None]:
    """What each ingredient cost the run per unit, as its line recorded."""
    lines = (
        await db.scalars(
            select(ProductionOrderLine).where(
                ProductionOrderLine.production_order_id == order_id
            )
        )
    ).all()
    return {line.child_template_id: line.unit_cost_snapshot for line in lines}


async def _put_the_ingredient_back(
    db: AsyncSession,
    organization_id: UUID,
    order: ProductionOrder,
    move: StockMoveDTO,
    user: UserContextDTO,
    history: dict[str, str],
    rates: dict[UUID, Decimal | None],
) -> None:
    """Return one draw of the run to the shelf, batch and date it came from.

    The record it left is still there, at what the run left of it, unless
    somebody removed it since; then the goods come back as a record of
    their own with the same batch and date. A batch the run took from may
    have been put on hold since — the goods still go back into it, held.
    """
    shelf = move.from_location_id
    if shelf is None:
        return
    record = await core_api.items.find_stock_row_async(
        db,
        organization_id,
        template_id=move.product_template_id,
        expiry_date=move.expiry_date,
        storage_location_id=shelf,
        lot_id=move.lot_id,
        owner_id=move.owner_id,
    )
    if record is None and move.lot_id is not None and move.expiry_date is not None:
        # A batch keeps its date on the batch; its records may carry none.
        record = await core_api.items.find_stock_row_async(
            db,
            organization_id,
            template_id=move.product_template_id,
            storage_location_id=shelf,
            lot_id=move.lot_id,
            owner_id=move.owner_id,
        )
    posts: list[RecordPostDTO] = []
    if record is not None:
        locked = await core_api.items.get_for_update_async(
            db, organization_id, record.id
        )
        if locked is not None:
            posts.append(
                RecordPostDTO(
                    item_id=locked.id,
                    new_quantity=(locked.quantity or Decimal('0')) + move.quantity,
                    history=history,
                )
            )
    if not posts:
        template = await core_api.product_templates.get_async(
            db, organization_id, move.product_template_id
        )
        await core_api.items.create_async(
            db,
            organization_id,
            ItemCreateDTO(
                name=template.name if template else 'Production ingredient',
                template_id=move.product_template_id,
                location_id=shelf,
                quantity=move.quantity,
                uom_id=template.uom_id if template else None,
                expiry_date=move.expiry_date,
                lot_id=move.lot_id,
                owner_id=move.owner_id,
            ),
            user=user,
            history_changes=history,
            post_the_change=False,
        )
    await core_api.stock.post_movement_async(
        db,
        organization_id,
        move.product_template_id,
        move.quantity,
        to_location_id=shelf,
        lot_id=move.lot_id,
        owner_id=move.owner_id,
        require_active_lot=False,
        reference_type=_REFERENCE_TYPE,
        reference_id=order.id,
        created_by=user.id,
        records=posts,
    )
    # Back at what it cost the run when it left, not at whatever the newest
    # layer of the product says today.
    await core_api.valuation.record_receipt_async(
        db,
        organization_id,
        move.product_template_id,
        move.quantity,
        rates.get(move.product_template_id),
    )
