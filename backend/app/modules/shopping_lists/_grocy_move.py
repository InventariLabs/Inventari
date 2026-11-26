"""The shopping lists' part of a move from Grocy.

Grocy keeps its shopping lists in the same database file as its stock. The
core files the products first (``app.services.items._grocy_import``), then
hands this module the file's rows with the products and units it matched
(:mod:`app.core.move_contributors`). Each Grocy list becomes a list of the
same name; an entry for a product links to the product the move made of it,
in the unit the move matched; an entry that is only a note keeps the note as
its name; one Grocy had ticked off arrives ticked off.

An entry keeps ``source='grocy'``. A list that already holds such entries
came across in an earlier move of the same file, and is left as it is.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select

from app.core.module_sdk import GrocyFile, GrocyShoppingListEntry, MoveMatches
from app.i18n.service import get_current_lang, get_shopping_label

from ._list_crud import create_shopping_list
from .models import ShoppingList, ShoppingListItem

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.contracts import UserContextDTO

#: The ``source`` an entry brought from Grocy carries.
GROCY_SOURCE = 'grocy'

#: What a list is called when Grocy left its name empty.
_UNNAMED = 'Grocy'


async def bring_grocy_shopping_lists_async(
    db: AsyncSession, user: UserContextDTO, grocy: GrocyFile, matches: MoveMatches
) -> str | None:
    """Grocy's shopping lists as lists here; the summary's sentence."""
    if user.organization_id is None or not grocy.shopping_list:
        return None
    org_id = user.organization_id
    lang = get_current_lang()
    by_list: dict[int, list[GrocyShoppingListEntry]] = {}
    for entry in grocy.shopping_list:
        by_list.setdefault(entry.list_id, []).append(entry)
    brought_before = await _lists_brought_before_async(db, org_id)

    lists = items = skipped = 0
    now = datetime.now(UTC)
    for entries in by_list.values():
        name = (entries[0].list_name or _UNNAMED)[:255]
        if name.strip().lower() in brought_before:
            skipped += len(entries)
            continue
        shopping_list = await create_shopping_list(db, org_id, user.id, name, lang)
        for entry in entries:
            db.add(_line(shopping_list.id, entry, grocy, matches, user.id, now))
            items += 1
        lists += 1
    await db.flush()

    sentence = get_shopping_label('grocy_lists_brought', lang).format(
        lists=lists, items=items
    )
    if skipped:
        sentence += '; ' + get_shopping_label('grocy_lists_skipped', lang).format(
            count=skipped
        )
    return sentence


async def _lists_brought_before_async(db: AsyncSession, org_id: UUID) -> set[str]:
    """The names of lists that hold entries an earlier Grocy move brought."""
    rows = await db.execute(
        select(func.lower(ShoppingList.name))
        .join(ShoppingListItem, ShoppingListItem.shopping_list_id == ShoppingList.id)
        .where(
            ShoppingList.organization_id == org_id,
            ShoppingListItem.source == GROCY_SOURCE,
        )
        .distinct()
    )
    return {name.strip() for (name,) in rows.all()}


def _line(
    list_id: UUID,
    entry: GrocyShoppingListEntry,
    grocy: GrocyFile,
    matches: MoveMatches,
    user_id: UUID,
    now: datetime,
) -> ShoppingListItem:
    product = grocy.products.get(entry.product_id) if entry.product_id else None
    return ShoppingListItem(
        shopping_list_id=list_id,
        template_id=matches.products.get(str(product.id)) if product else None,
        name=(product.name if product else entry.note or _UNNAMED)[:255],
        # Grocy keeps a note-only entry at zero; a line here is at least one.
        quantity=entry.amount if entry.amount > 0 else Decimal(1),
        uom_id=matches.units.get(entry.unit_id) if entry.unit_id else None,
        notes=entry.note if product else None,
        is_purchased=entry.done,
        purchased_at=now if entry.done else None,
        purchased_by=user_id if entry.done else None,
        source=GROCY_SOURCE,
    )
