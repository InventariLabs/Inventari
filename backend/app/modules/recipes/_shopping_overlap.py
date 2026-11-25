"""Say which freshly written shopping lines another open list already carries.

Two doors write a list of their own — a recipe's "add what is missing" and a
meal plan's "generate shopping list" — and a cook who used both had the same
flour on two lists with nothing on either screen saying so. Merging would
change a list somebody may be shopping from, so the lists stay as written and
the answer names the overlap: which goods, on which list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.modules.shopping_lists.shopping_lists_api import shopping_lists_api

from ._shopping_rule import GoodsKey, goods_key
from .schemas import ListedElsewhere

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.contracts import ShoppingListItemCreateDTO, UomDTO


async def lines_listed_elsewhere(
    db: AsyncSession,
    org_id: UUID,
    written: Iterable[ShoppingListItemCreateDTO],
    *,
    list_id: UUID,
    uoms_by_id: Mapping[UUID, UomDTO],
) -> list[ListedElsewhere]:
    """The *written* lines that a list other than *list_id* still has to buy.

    A line matches on name and on what its unit measures (``goods_key``), so
    1 kg of flour here meets 300 g of it on another list. A line ticked off
    elsewhere is bought and is no overlap.
    """
    wanted = {
        goods_key(line.name, line.uom_id, uoms_by_id): line.name for line in written
    }
    if not wanted:
        return []
    overlaps: list[ListedElsewhere] = []
    seen: set[tuple[GoodsKey, UUID]] = set()
    for other, item in await shopping_lists_api.open_lines_async(
        db, org_id, exclude_list_id=list_id
    ):
        key = goods_key(item.name, item.uom_id, uoms_by_id)
        if key not in wanted or (key, other.id) in seen:
            continue
        seen.add((key, other.id))
        overlaps.append(
            ListedElsewhere(name=wanted[key], list_id=other.id, list_name=other.name)
        )
    return overlaps
