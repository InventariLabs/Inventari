"""Public API for shopping list operations — exposed for other modules (e.g., recipes).

Follows the approvals_api / warehouse_api pattern: module owns its API,
other modules import the singleton directly.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    ShoppingListDTO,
    ShoppingListItemCreateDTO,
    ShoppingListItemDTO,
)
from app.i18n import Language
from app.i18n.service import get_current_lang, get_error_message

if TYPE_CHECKING:
    from app.modules.shopping_lists.models import ShoppingList


async def _require_module_enabled(db: AsyncSession, org_id: UUID) -> None:
    """Cross-Module API Contracts §3: the API must be safe to call when the
    module is disabled — writers raise a clean PermissionError (mapped to 403
    by the consumer's service-error decorator) instead of writing rows the
    user has no path to reach."""
    from app.core.modules import is_module_enabled_async

    if not await is_module_enabled_async(db, org_id, 'shopping_lists'):
        raise PermissionError(
            get_error_message('shopping_lists_module_disabled', get_current_lang())
        )


class ShoppingListsAPI:
    """Public API for shopping list operations.

    Provides a stable interface for other modules (e.g., recipes) to create
    shopping lists and add items without importing module internals directly.
    """

    async def create_shopping_list_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        created_by: UUID,
        name: str | None,
        lang: Language = 'en',
    ) -> ShoppingListDTO:
        """Async: create a new shopping list with optional auto-generated name.

        Delegates to _list_crud.create_shopping_list — the duplicated
        name-generation copy here used a naive today_start (bug: naive vs
        the timezone-aware created_at column); the shared path computes it
        in UTC.
        """
        await _require_module_enabled(db, org_id)
        from ._list_crud import create_shopping_list

        shopping_list = await create_shopping_list(db, org_id, created_by, name, lang)
        return ShoppingListDTO.model_validate(shopping_list)

    async def active_list_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        created_by: UUID,
        lang: Language = 'en',
    ) -> ShoppingListDTO:
        """The list things go on now: the newest active one, made if there is none.

        The server side of the interface's "put it on the shopping list" — the
        list the reader is already filling, not a new one per click.
        """
        await _require_module_enabled(db, org_id)
        from app.modules.shopping_lists.models import ShoppingList, ShoppingListStatus

        newest = (
            await db.scalars(
                select(ShoppingList)
                .where(
                    ShoppingList.organization_id == org_id,
                    ShoppingList.status == ShoppingListStatus.ACTIVE.value,
                )
                .order_by(ShoppingList.created_at.desc())
                .limit(1)
            )
        ).first()
        if newest is not None:
            return ShoppingListDTO.model_validate(newest)
        return await self.create_shopping_list_async(db, org_id, created_by, None, lang)

    async def add_items_async(
        self,
        db: AsyncSession,
        list_id: UUID,
        items: list[ShoppingListItemCreateDTO],
        org_id: UUID,
    ) -> list[ShoppingListItemDTO]:
        """Async: add multiple items to a shopping list of *org_id*.

        ``org_id`` is not a convenience: the method used to be addressed by a
        bare ``list_id``, so whether the list belonged to the caller was the
        caller's word. Both callers in the tree happen to check — which is
        what a confused deputy looks like right up until the third one is
        written. A list that is not this organization's, or not there at all,
        is refused; the old code skipped the module gate for a missing list
        and inserted the rows anyway, pointing them at nothing.

        Quantities are guarded here, at the door — not borrowed from the
        consumers. The contract DTO's only bound is ``gt=0`` and this method
        builds rows directly, bypassing both places the protection lives
        today (the quantizing validators on ``ShoppingListItemCreate`` and
        the zero refusal in ``bulk_add_items``); both of today's callers
        quantize before they call, which is a guard that holds right up
        until the third caller does not. The column is numeric(12, 3) and
        rounds silently, so a quantity below its own first digit is a stored
        zero no read schema accepts — the list stops opening and nothing in
        the interface can undo it. Quantize here, refuse the zero the
        rounding produces, and answer the whole call, not the remainder
        after the first offender.

        The response is read back from the rows after the flush, not
        validated from the objects built before it: a numeric column rounds
        silently (quantity at three places, estimated_price at two), and
        ``db.refresh(item, ['category'])`` answered only the relationship.
        """
        from app.core.exceptions import ServiceRejectionError
        from app.modules.shopping_lists.models import ShoppingListItem
        from app.schemas.validators import QUANTITY_MAX, quantize_quantity

        await self._own_list_or_404_async(db, list_id, org_id)
        await _require_module_enabled(db, org_id)

        from app.core.public_api import core_api

        uom_ids = {item_in.uom_id for item_in in items if item_in.uom_id is not None}
        if uom_ids:
            found = await core_api.uoms.existing_ids_async(db, uom_ids, org_id)
            missing = uom_ids - found
            if missing:
                raise ServiceRejectionError(
                    'shopping_list_item_uom_unknown',
                    uom_id=str(next(iter(missing))),
                )

        # The product references get the same answer the CRUD door gives:
        # an id no visible row answers is a foreign-key 500 at the INSERT,
        # refused here as a keyed rejection instead — one batched question
        # per reference family, scoped to what the organization can see.
        item_ids = {i.item_id for i in items if i.item_id is not None}
        if item_ids:
            found = await core_api.items.existing_ids_async(db, org_id, item_ids)
            missing = item_ids - found
            if missing:
                raise ServiceRejectionError(
                    'shopping_list_item_item_unknown',
                    item_id=str(next(iter(missing))),
                )
        category_ids = {i.category_id for i in items if i.category_id is not None}
        if category_ids:
            found = await core_api.categories.existing_ids_async(
                db, org_id, category_ids
            )
            missing = category_ids - found
            if missing:
                raise ServiceRejectionError(
                    'shopping_list_item_category_unknown',
                    category_id=str(next(iter(missing))),
                )
        template_ids = {i.template_id for i in items if i.template_id is not None}
        if template_ids:
            found_templates = await core_api.product_templates.get_many_async(
                db, org_id, list(template_ids)
            )
            missing = template_ids - set(found_templates)
            if missing:
                raise ServiceRejectionError(
                    'shopping_list_item_template_unknown',
                    template_id=str(next(iter(missing))),
                )

        # The twin of _item_crud's zero refusal — same key, same answer,
        # held at the door this CRUD path never sees. The ceiling rides
        # here for the same reason: the column is numeric(12, 3), and a
        # quantity past what it stores would answer with the driver's
        # overflow instead of a sentence.
        stored_quantities: list[Decimal] = []
        for item_in in items:
            stored = quantize_quantity(item_in.quantity)
            if stored is None or stored <= 0:
                raise ServiceRejectionError(
                    'shopping_list_item_quantity_rounds_to_zero',
                    quantity=item_in.quantity,
                )
            if stored > QUANTITY_MAX:
                raise ServiceRejectionError(
                    'shopping_list_item_quantity_above_ceiling',
                    quantity=item_in.quantity,
                    ceiling=QUANTITY_MAX,
                )
            stored_quantities.append(stored)

        created_items = []
        for item_in, stored in zip(items, stored_quantities, strict=True):
            item = ShoppingListItem(
                shopping_list_id=list_id,
                item_id=item_in.item_id,
                category_id=item_in.category_id,
                template_id=item_in.template_id,
                name=item_in.name,
                quantity=stored,
                uom_id=item_in.uom_id,
                notes=item_in.notes,
                note_data=item_in.note_data,
                estimated_price=item_in.estimated_price,
                priority=item_in.priority or 0,
                source=item_in.source or 'manual',
            )
            db.add(item)
            created_items.append(item)
        await db.flush()
        for item in created_items:
            await db.refresh(item, ['quantity', 'estimated_price', 'category'])
        return [ShoppingListItemDTO.model_validate(i) for i in created_items]

    async def _own_list_or_404_async(
        self, db: AsyncSession, list_id: UUID, org_id: UUID
    ) -> ShoppingList:
        """The one place this API decides a list is the caller's to touch."""
        from app.core.exceptions import NotFoundException
        from app.modules.shopping_lists.models import ShoppingList

        result = await db.scalars(
            select(ShoppingList).where(
                ShoppingList.id == list_id,
                ShoppingList.organization_id == org_id,
            )
        )
        shopping_list = result.first()
        if shopping_list is None:
            raise NotFoundException('shopping_list')
        return shopping_list

    async def get_list_items_async(
        self,
        db: AsyncSession,
        list_id: UUID,
        org_id: UUID,
    ) -> list[ShoppingListItemDTO]:
        """Async: return all items of a shopping list (checked and unchecked)."""
        from app.modules.shopping_lists.models import ShoppingListItem

        await self._own_list_or_404_async(db, list_id, org_id)

        result = await db.scalars(
            select(ShoppingListItem).where(ShoppingListItem.shopping_list_id == list_id)
        )
        return [ShoppingListItemDTO.model_validate(i) for i in result.all()]

    async def open_lines_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        *,
        exclude_list_id: UUID | None = None,
    ) -> list[tuple[ShoppingListDTO, ShoppingListItemDTO]]:
        """Async: the lines still to buy on the organization's active lists.

        A line already ticked off is bought and no longer asks for anything,
        and a completed or archived list is not one anyone shops from. The
        list being written to is left out by *exclude_list_id*, so a caller
        comparing its own lines against "the other lists" does not meet
        itself.
        """
        from app.modules.shopping_lists.models import (
            ShoppingList,
            ShoppingListItem,
            ShoppingListStatus,
        )

        query = (
            select(ShoppingList, ShoppingListItem)
            .join(
                ShoppingListItem, ShoppingListItem.shopping_list_id == ShoppingList.id
            )
            .where(
                ShoppingList.organization_id == org_id,
                ShoppingList.status == ShoppingListStatus.ACTIVE.value,
                ShoppingListItem.is_purchased.is_(False),
            )
            .order_by(ShoppingList.created_at, ShoppingListItem.name)
        )
        if exclude_list_id is not None:
            query = query.where(ShoppingList.id != exclude_list_id)
        rows = (await db.execute(query)).all()
        return [
            (
                ShoppingListDTO.model_validate(shopping_list),
                ShoppingListItemDTO.model_validate(item),
            )
            for shopping_list, item in rows
        ]

    async def get_shopping_list_async(
        self,
        db: AsyncSession,
        list_id: UUID,
        org_id: UUID,
    ) -> ShoppingListDTO | None:
        """Async: get a shopping list by ID, scoped to organization."""
        from app.modules.shopping_lists.models import ShoppingList

        result = await db.scalars(
            select(ShoppingList).where(
                ShoppingList.id == list_id,
                ShoppingList.organization_id == org_id,
            )
        )
        shopping_list = result.first()
        if shopping_list is None:
            return None
        return ShoppingListDTO.model_validate(shopping_list)


shopping_lists_api = ShoppingListsAPI()

__all__ = ['shopping_lists_api']
