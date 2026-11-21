"""The batch a run files its output under: its name, its dates, its hold.

Every run puts its output in a batch. A person may name it; a run nobody
named it for names its own — the run's day and a counter, unique among the
product's batches in the organization (``20261115-1``, then ``20261115-2``
for the second run of that product that day). The batch carries the run's
day as its production date and a best-before of that day plus the product's
shelf life, which the person closing the run may change; the output record
carries the same date, so FEFO, the expiry views and To do read made goods
the way they read received ones.

The shelf life is this module's own fact about a product
(``maker_shelf_lives``). A module that dates its output another way opens
its batch with its own dates through ``core_api.stock.get_or_create_lot_async``
and never reads this table: the dates belong to the batch, not to the card.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import StockLotDTO, UserContextDTO
from app.core.db_utils import acquire_advisory_lock
from app.core.exceptions import EntityNotFoundError, ServiceRejectionError
from app.core.public_api import core_api

from ._schemas_batches import RunBatchRead
from .models import MakerShelfLife, ProductionOrder, ProductionPortion

#: The states a batch is on hold in.
HELD_STATUSES = frozenset({'quarantined', 'held'})


async def shelf_lives_async(
    db: AsyncSession, organization_id: UUID, template_ids: list[UUID]
) -> dict[UUID, int]:
    """The shelf life of each product that has one, in days, batched."""
    if not template_ids:
        return {}
    rows = await db.execute(
        select(
            MakerShelfLife.product_template_id, MakerShelfLife.shelf_life_days
        ).where(
            MakerShelfLife.organization_id == organization_id,
            MakerShelfLife.product_template_id.in_(template_ids),
        )
    )
    return {row[0]: row[1] for row in rows.all()}


async def get_shelf_life_async(
    db: AsyncSession, organization_id: UUID, template_id: UUID
) -> int | None:
    """One product's shelf life in days, or None when nobody named one."""
    return (await shelf_lives_async(db, organization_id, [template_id])).get(
        template_id
    )


async def set_shelf_life_async(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
    shelf_life_days: int | None,
) -> int | None:
    """Set the product's shelf life, or clear it with ``None``.

    The product must be one the organization can see; the row is the
    organization's own either way.
    """
    template = await core_api.product_templates.get_async(
        db, organization_id, template_id
    )
    if template is None:
        raise EntityNotFoundError('product_template', str(template_id))
    # Two people setting it at once is a lost update, not a second row.
    await acquire_advisory_lock(db, f'maker_shelf_life:{organization_id}:{template_id}')
    if shelf_life_days is None:
        await db.execute(
            delete(MakerShelfLife).where(
                MakerShelfLife.organization_id == organization_id,
                MakerShelfLife.product_template_id == template_id,
            )
        )
        return None
    row = (
        await db.execute(
            select(MakerShelfLife)
            .where(
                MakerShelfLife.organization_id == organization_id,
                MakerShelfLife.product_template_id == template_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(
            MakerShelfLife(
                organization_id=organization_id,
                product_template_id=template_id,
                shelf_life_days=shelf_life_days,
            )
        )
    else:
        row.shelf_life_days = shelf_life_days
    await db.flush()
    return shelf_life_days


async def best_before_for_run(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
    run_day: date,
    asked: date | None,
) -> date | None:
    """The best-before the run's batch carries.

    What the person closing the run typed, else the run's day plus the
    product's shelf life, else none. A date before the day the goods were
    made is refused: no batch keeps for less than nothing.
    """
    if asked is not None:
        if asked < run_day:
            raise ServiceRejectionError(
                'production_best_before_before_made',
                best_before=asked.isoformat(),
                made=run_day.isoformat(),
            )
        return asked
    days = await get_shelf_life_async(db, organization_id, template_id)
    return run_day + timedelta(days=days) if days else None


async def next_batch_name(
    db: AsyncSession, organization_id: UUID, template_id: UUID, run_day: date
) -> str:
    """A batch name of the run's day no batch of the product carries yet.

    Called with the product's card locked by the run (the completion takes
    its output's anchor before anything is drawn), so two runs of one
    product closing at once read each other's batch and count on.
    """
    taken = {
        lot.name
        for lot in await core_api.stock.list_lots_async(
            db, organization_id, template_id
        )
    }
    prefix = run_day.strftime('%Y%m%d')
    counter = 1
    while f'{prefix}-{counter}' in taken:
        counter += 1
    return f'{prefix}-{counter}'


async def _order_with_output_or_refuse(
    db: AsyncSession, organization_id: UUID, order_id: UUID
) -> ProductionOrder:
    order = await db.scalar(
        select(ProductionOrder).where(
            ProductionOrder.organization_id == organization_id,
            ProductionOrder.id == order_id,
        )
    )
    if order is None:
        raise EntityNotFoundError('production_order', str(order_id))
    if order.output_lot_id is None:
        raise ServiceRejectionError('production_output_batch_missing')
    return order


async def lots_of_run_async(
    db: AsyncSession, organization_id: UUID, order: ProductionOrder
) -> list[StockLotDTO]:
    """Every batch the run's output was filed under, the run's own first.

    A run filled in portions files each portion under the batch its person
    named, and its closing quantity under one more, so the output is not one
    batch: the run's page, its record, its labels and its hold all speak of
    every one of them. A run completed in one step has exactly one.
    """
    if order.output_lot_id is None:
        return []
    names = (
        await db.scalars(
            select(ProductionPortion.lot_name)
            .where(
                ProductionPortion.organization_id == organization_id,
                ProductionPortion.production_order_id == order.id,
            )
            .order_by(ProductionPortion.made_on, ProductionPortion.created_at)
        )
    ).all()
    lots = await core_api.stock.list_lots_async(
        db, organization_id, order.output_template_id
    )
    by_name = {lot.name: lot for lot in lots}
    own = next((lot for lot in lots if lot.id == order.output_lot_id), None)
    found: dict[UUID, StockLotDTO] = {own.id: own} if own is not None else {}
    for name in names:
        lot = by_name.get(name or '')
        if lot is not None:
            found.setdefault(lot.id, lot)
    return list(found.values())


def run_batch_reads(
    lots: list[StockLotDTO], made: dict[UUID, Decimal] | None = None
) -> list[RunBatchRead]:
    """The batches of a run as the screens read them.

    *made* is the quantity the run filed under each batch, when the caller
    knows it (the batch record).
    """
    return [
        RunBatchRead(
            lot_id=lot.id,
            lot_name=lot.name,
            status=lot.status,
            status_reason=lot.status_reason if lot.status in HELD_STATUSES else None,
            best_before=lot.expiry_date or lot.use_by_date,
            quantity=(made or {}).get(lot.id),
        )
        for lot in lots
    ]


async def hold_output_async(
    db: AsyncSession,
    organization_id: UUID,
    order_id: UUID,
    user: UserContextDTO,
    reason: str | None,
) -> list[StockLotDTO]:
    """Put every batch of the run's output on hold — Core's quarantine.

    A held batch stays on its shelf and is offered to no draw: no other
    run's ingredients, no dispatch, no pick, until it is released. The
    run's own batch comes first in the answer.
    """
    order = await _order_with_output_or_refuse(db, organization_id, order_id)
    held: list[StockLotDTO] = []
    for lot in await lots_of_run_async(db, organization_id, order):
        quarantined = await core_api.stock.quarantine_lot_async(
            db,
            organization_id,
            lot.id,
            reason.strip() if reason else None,
            user_id=user.id,
        )
        if quarantined is None:
            raise EntityNotFoundError('stock_lot', str(lot.id))
        held.append(quarantined)
    return held


async def release_output_async(
    db: AsyncSession,
    organization_id: UUID,
    order_id: UUID,
    user: UserContextDTO,
) -> list[StockLotDTO]:
    """Release the batches of the run's output that are on hold — Core's release.

    A batch of the run that is not on hold keeps the state it is in: a
    recalled one is not a hold this button put there.
    """
    order = await _order_with_output_or_refuse(db, organization_id, order_id)
    released: list[StockLotDTO] = []
    for lot in await lots_of_run_async(db, organization_id, order):
        if lot.status not in HELD_STATUSES:
            released.append(lot)
            continue
        freed = await core_api.stock.release_lot_async(
            db, organization_id, lot.id, user_id=user.id
        )
        if freed is None:
            raise EntityNotFoundError('stock_lot', str(lot.id))
        released.append(freed)
    return released
