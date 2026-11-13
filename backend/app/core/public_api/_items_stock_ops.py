from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ItemAction, ItemDTO, UserContextDTO
from app.core.exceptions import ServiceRejectionError
from app.core.public_api._access import writes
from app.schemas.item import ItemMove, ItemQuantityUpdate
from app.services.items import (
    get_by_id_async,
    get_by_id_for_update_async,
    move_item,
    post_opening_balance_async,
    update_quantity,
)
from app.services.items._open_package import open_to_take_part_async


class CoreItemsStockOpsMixin:
    """Stock operation methods for CoreItemsAPI (quantity, transfer, consume, discard, meta_data)."""

    @writes
    async def update_quantity_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        item_id: UUID,
        quantity: Decimal,
        *,
        user_id: UUID,
        source_document_id: UUID | None = None,
        history_changes: dict[str, Any] | None = None,
        sync_valuation: bool = True,
        post_the_change: bool = True,
        lot_id: UUID | None = None,
        move_reference_type: str = 'item',
        move_reference_id: UUID | None = None,
    ) -> ItemDTO | None:
        """Set an item's quantity and post the change to the ledger.

        *lot_id* names the batch the change belongs to, for a caller that
        knows one — a count that named a batch; a record that names no batch
        takes it. Without it the change lands on the record's own batch and
        owner (see ``_post_the_change_async``). *post_the_change* is False
        for a caller that posts the movement and the cost itself — a
        document, a production run, ``core_api.stock.post_movement_async``.
        *move_reference_type* names the movement this produces, and
        *move_reference_id* what produced it — the stock take a correction
        came out of. Without the second, the ledger holds a movement
        pointing back at the item it changed, which is where it already
        is: a count's correction and a quantity typed in by hand read the
        same.
        """
        # Lock the item row so two concurrent quantity updates cannot both read
        # the same base quantity and lose an update.
        item = await get_by_id_for_update_async(db, organization_id, item_id)
        if item is None:
            return None

        quantity_update = ItemQuantityUpdate(quantity=quantity)
        updated = await update_quantity(
            db=db,
            item=item,
            quantity_update=quantity_update,
            user_id=user_id,
            source_document_id=source_document_id,
            history_changes=history_changes,
            sync_valuation=sync_valuation,
            post_the_change=post_the_change,
            lot_id=lot_id,
            move_reference_type=move_reference_type,
            move_reference_id=move_reference_id,
        )
        return ItemDTO.model_validate(updated)

    @writes
    async def post_opening_balance_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        item_id: UUID,
        *,
        template_id: UUID,
        holding: Decimal,
        user_id: UUID | None,
        location_id: UUID | None = None,
    ) -> None:
        """Post what a record held before it had a card as its opening balance.

        For a door that has just given a record its card
        (:meth:`bind_template_async`): the stock the record held was never in
        the register, and the door has to say what stood there before it moves
        any of it. This writes the movement marked ``opening_balance`` and
        the cost layer by the one Core rule every door takes, so a module
        keeps no copy of it.

        *holding* is what the record held before the door changed it, in the
        record's own unit. *location_id* is the shelf it stood on; left out,
        the record's own.
        """
        item = await get_by_id_async(db, organization_id, item_id)
        if item is None:
            raise ServiceRejectionError('item_not_found')
        await post_opening_balance_async(
            db,
            item,
            template_id=template_id,
            quantity=holding,
            user_id=user_id,
            location_id=location_id,
        )

    @writes
    async def transfer_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        item_id: UUID,
        to_storage_location_id: UUID,
        *,
        user_id: UUID,
        source_document_id: UUID | None = None,
        notes: str | None = None,
        history_changes: dict[str, Any] | None = None,
        history_action: ItemAction = ItemAction.MOVED,
        post_the_change: bool = True,
    ) -> ItemDTO | None:
        # Lock the item for the move (mutates location + stock); two concurrent
        # transfers of the same item must serialize.
        item = await get_by_id_for_update_async(db, organization_id, item_id)
        if item is None:
            return None

        move_data = ItemMove(to_location_id=to_storage_location_id, notes=notes)
        user = UserContextDTO(id=user_id, organization_id=organization_id)
        moved = await move_item(
            db=db,
            item=item,
            move_data=move_data,
            user=user,
            source_document_id=source_document_id,
            history_changes=history_changes,
            history_action=history_action,
            post_the_change=post_the_change,
        )
        return ItemDTO.model_validate(moved)

    @writes
    async def update_meta_data_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        item_id: UUID,
        namespace: str,
        data: dict[str, Any],
    ) -> ItemDTO | None:
        """Update item meta_data in a namespaced way."""
        from sqlalchemy.orm.attributes import flag_modified

        # Lock the item: meta_data is a read-modify-write on a JSONB column,
        # so two concurrent updates would lose one namespace.
        item = await get_by_id_for_update_async(db, organization_id, item_id)
        if item is None:
            return None

        meta = dict(item.meta_data or {})
        meta[namespace] = {**meta.get(namespace, {}), **data}
        item.meta_data = meta
        flag_modified(item, 'meta_data')
        await db.flush()
        return ItemDTO.model_validate(item)

    @writes
    async def open_to_take_part_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        item_id: UUID,
        *,
        user_id: UUID,
    ) -> ItemDTO | None:
        """Open the package a part is about to be taken from (writes the opening).

        Returns the record that is now the open package: the same one when it
        already was open, held a single unit, or is not a package at all, and
        a new one split off when it held several. The caller takes its amount
        from the record this returns.
        """
        item = await get_by_id_for_update_async(db, organization_id, item_id)
        if item is None:
            return None
        opened = await open_to_take_part_async(
            db,
            item,
            UserContextDTO(id=user_id, organization_id=organization_id),
        )
        return ItemDTO.model_validate(opened)
