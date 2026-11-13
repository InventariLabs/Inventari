from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    ItemCreateDTO,
    ItemDTO,
    ItemUpdateDTO,
    UserContextDTO,
)
from app.core.exceptions import ContractViolationError
from app.core.public_api._access import writes
from app.schemas.item import ItemCreate, ItemUpdate
from app.services.items import (
    bind_item_to_template_async,
    create_item,
    delete_item,
    get_any_by_id_async,
    get_by_id_async,
    purge_item,
    update_item,
)


class CoreItemsWritesMixin:
    """Write methods for CoreItemsAPI (create, update, delete, purge)."""

    @writes
    async def create_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        data: ItemCreateDTO,
        user: UserContextDTO,
        *,
        source_document_id: UUID | None = None,
        history_changes: dict[str, Any] | None = None,
        post_the_change: bool = True,
        unit_confirmed_over_template: bool = False,
    ) -> ItemDTO:
        """Create an item through the standard service pipeline.

        The service files the record in ``user.organization_id`` and checks
        the location and category against it, so ``organization_id`` is the
        caller's statement of where the record belongs. A caller whose
        organization differs from its user's is refused rather than having
        the record land, unasked, in the user's. *post_the_change* is False
        for a caller that posts the new stock's movement itself.

        ``unit_confirmed_over_template`` is the operator's answer from the
        calling screen, for a caller whose payload was typed there — a
        document line naming a card in another unit stops at the create's
        unit gate unless the difference rides in confirmed, the same door
        the request body's own field opens (see ``ItemCreate``). A caller
        that says nothing gets the honest refusal.
        """
        if organization_id != user.organization_id:
            raise ContractViolationError(
                'core_api.items.create_async: organization_id does not match the '
                'organization of the user the record is written for'
            )
        payload = data.model_dump()
        lot_id = payload.pop('lot_id')
        owner_id = payload.pop('owner_id')
        item_create = ItemCreate(**payload)
        item = await create_item(
            db=db,
            item_in=item_create,
            user=user,
            source_document_id=source_document_id,
            history_changes=history_changes,
            post_the_change=post_the_change,
            unit_confirmed_over_template=unit_confirmed_over_template,
            lot_id=lot_id,
            owner_id=owner_id,
        )
        return ItemDTO.model_validate(item)

    @writes
    async def update_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        item_id: UUID,
        data: ItemUpdateDTO,
        user: UserContextDTO,
    ) -> ItemDTO | None:
        item = await get_by_id_async(db, organization_id, item_id)
        if not item:
            return None

        item_update = ItemUpdate(**data.model_dump(exclude_unset=True))
        updated = await update_item(db=db, item=item, item_in=item_update, user=user)
        return ItemDTO.model_validate(updated)

    @writes
    async def bind_template_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        item_id: UUID,
        template_id: UUID,
        *,
        user_id: UUID | None = None,
        source_document_id: UUID | None = None,
        unit_confirmed_over_template: bool = False,
    ) -> ItemDTO | None:
        """Point a record at its product card — the link, and the paper behind it.

        For a record that predates its card: a document moving the goods
        has to land them in the per-product ledger, and the ledger is kept
        per card. The write is the link — quantity and identity are the
        record's own; a record naming no unit takes its card's, the unit the
        ledger books it in — but it is
        not invisible,
        and it is not exempt from the unit rule: the record keeps the
        history row and the organization's journal keeps the entry the edit
        path leaves when it moves this column, and a record kept in another
        unit than its card is refused by name instead of relabelled — unless
        the difference was confirmed (*unit_confirmed_over_template*, the
        operator's answer on the calling document's execution screen), in
        which case the record is restated into the card's unit and the
        choice is kept in its history.
        """
        item = await get_by_id_async(db, organization_id, item_id)
        if item is None:
            return None
        await bind_item_to_template_async(
            db,
            item,
            organization_id,
            template_id,
            user_id=user_id,
            source_document_id=source_document_id,
            unit_confirmed_over_template=unit_confirmed_over_template,
        )
        return ItemDTO.model_validate(item)

    @writes
    async def soft_delete_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        item_id: UUID,
        user: UserContextDTO,
        reason: str | None = None,
        notes: str | None = None,
    ) -> bool:
        item = await get_by_id_async(db, organization_id, item_id)
        if not item:
            return False

        await delete_item(db, item, user, reason=reason, notes=notes)
        return True

    @writes
    async def purge_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        item_id: UUID,
        user: UserContextDTO,
        reason: str | None = None,
    ) -> bool:
        item = await get_any_by_id_async(db, organization_id, item_id)
        if not item:
            return False

        await purge_item(db, item, user, reason=reason)
        return True
