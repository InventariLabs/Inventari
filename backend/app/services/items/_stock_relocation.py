"""Moving one record's stock from one shelf to another, in one place.

Two paths did this. ``move_service`` refused the move when the source quant
still held reservations — decrementing it would have released
``reserved_quantity`` while the ``StockReservation`` rows went on pointing at
a quant that had been drained, so a later per-document release would take the
stock off a shelf twice — and it carried the lots across, so a receipt's
batch travelled with the goods instead of being debited from a phantom
lot-less quant.

The bulk edit did neither. It called decrement-then-increment on a flat
quantity, which is the exact sequence the guard exists to prevent, and merged
every lot into one nameless heap on arrival. Selecting fifty records and
setting their location was therefore a different operation from moving them
one at a time — quieter, and wrong in two ways at once.

One function now, called from both — and the one place the movement itself is
recorded. Neither path wrote a ``StockMove``, so goods carried from one of the
organization's own shelves to another left no row in a register whose own
subtitle offers "what moved between your own places", and whose "Moved" filter
could therefore never match anything. Recording it here rather than in the two
callers is what keeps the single move and the bulk edit from drifting apart
again, which is the whole reason this function exists.

The doors that write a record's shelf all reach it through
``carry_record_stock_async``: the move, the bulk edit, and the single edit
behind ``PUT /items``, ``core_api.items.update_async`` and a re-imported sheet.
The last three wrote the column and nothing else, so the record stood on one
shelf and its stock on another.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.services._stock_quant_ops import lock_stock_async, post_movement_async

if TYPE_CHECKING:
    from app.models.item import Item


async def relocate_stock_async(
    db: AsyncSession,
    *,
    org_id: UUID,
    template_id: UUID,
    from_location_id: UUID,
    to_location_id: UUID,
    quantity: Decimal,
    item_id: UUID,
    user_id: UUID | None = None,
    lot_id: UUID | None = None,
    owner_id: UUID | None = None,
) -> None:
    """Carry *quantity* of the record *item_id* from one location to the other.

    Raises ``ValueError`` when the source holds reservations. The goods are
    the record's own grain — its batch *lot_id* and its owner *owner_id* —
    and arrive as the same grain; the movement is posted by
    ``post_movement_async``, one ``StockMove`` carrying both ends, which is
    what the moves register reads. Moving is not consuming, so a held batch
    moves too: that is how quarantined stock reaches a quarantine area.

    *user_id* is who carried the goods; the movement names the record and
    them.
    """
    from app.models.stock_quants_from_records import stock_quants_from_records
    from app.models.storage_location import StorageLocation

    # The destination decides which organization ends up holding the stock,
    # so it is checked here and not only by the callers. Both of them
    # validate it today; this function creating stock on any location id it
    # is handed is what made that a matter of caller discipline.
    destination = await db.get(StorageLocation, to_location_id)
    if destination is None or destination.organization_id != org_id:
        raise ServiceRejectionError('relocation_destination_foreign')

    # Both shelves before either is written: a record carried from A to B
    # took A and then B, and met one carried from B to A holding B.
    await lock_stock_async(
        db,
        org_id,
        keys=[(template_id, from_location_id), (template_id, to_location_id)],
    )
    # The holds are the reservation rows, read through the records' view
    # under the lock above.
    held = await db.scalar(
        select(
            func.coalesce(func.sum(stock_quants_from_records.c.reserved_quantity), 0)
        ).where(
            stock_quants_from_records.c.organization_id == org_id,
            stock_quants_from_records.c.product_template_id == template_id,
            stock_quants_from_records.c.storage_location_id == from_location_id,
        )
    )
    if held and held > 0:
        raise ServiceRejectionError('relocation_blocked_by_reservations')

    await post_movement_async(
        db,
        org_id,
        template_id,
        quantity,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        lot_id=lot_id,
        owner_id=owner_id,
        require_active_lot=False,
        reference_type='item',
        reference_id=item_id,
        created_by=user_id,
    )


async def carry_record_stock_async(
    db: AsyncSession,
    item: Item,
    *,
    from_location_id: UUID | None,
    quantity: Decimal | None,
    user_id: UUID | None = None,
) -> None:
    """The record now stands on another shelf; its stock goes with it.

    Every door that writes a record's shelf calls this after writing it — the
    move, the single edit, the bulk edit, and whatever reaches them (the
    public API, a re-imported sheet). Three of those five used to set the
    column and write nothing else, so the record moved and the register did
    not say how.

    *quantity* is what the record held on the old shelf — before any
    quantity change made in the same request, which the caller applies
    afterwards on the new shelf. A record without a card or without stock
    has nothing in the register to carry, and neither has one that stood on
    no shelf before (which the schema no longer allows).
    """
    to_location_id = item.storage_location_id
    if (
        to_location_id is None
        or from_location_id is None
        or from_location_id == to_location_id
        or item.template_id is None
        or not quantity
        or quantity <= 0
    ):
        return
    await relocate_stock_async(
        db,
        org_id=item.organization_id,
        template_id=item.template_id,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        quantity=quantity,
        item_id=item.id,
        user_id=user_id,
        lot_id=item.lot_id,
        owner_id=item.owner_id,
    )


def shelf_change_keys(
    items: list[Item], to_location_id: UUID | None
) -> list[tuple[UUID, UUID]]:
    """The ``(product, shelf)`` groups *items* leave and join on a shelf change.

    The groups of a record whose shelf actually moves: the one it stands on
    and the one the batch joins. A record already on the target shelf, one
    without a card (no group, no anchor) and a batch that names no target
    contribute nothing. Shared with the batch door, which merges these with
    its quantity groups and locks them all in one call.
    """
    return [
        key
        for item in items
        if item.template_id is not None
        and to_location_id is not None
        and item.storage_location_id != to_location_id
        for key in (
            (item.template_id, item.storage_location_id),
            (item.template_id, to_location_id),
        )
    ]


async def lock_shelf_change_async(
    db: AsyncSession, items: list[Item], to_location_id: UUID | None
) -> None:
    """Lock the groups *items* leave and join, before their shelf is written.

    A record with a card names its group's anchor by a foreign key, and the
    lock is what creates the anchor of a shelf the product has never stood
    on. So the lock comes before the column changes — not in
    :func:`carry_record_stock_async`, which runs after it and, for a record
    with no stock, not at all. Every record of a batch in one call, so two
    batches crossing the same shelves wait for each other instead of
    closing a circle.
    """
    keys = shelf_change_keys(items, to_location_id)
    if keys:
        await lock_stock_async(db, items[0].organization_id, keys=keys)
