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

from .schemas import ListedElsewhere

if TYPE_CHECKING:
    from collections.abc import Iterable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.contracts import ShoppingListItemCreateDTO


async def lines_listed_elsewhere(
    db: AsyncSession,
    org_id: UUID,
    written: Iterable[ShoppingListItemCreateDTO],
    *,
    list_id: UUID,
) -> list[ListedElsewhere]:
    """The *written* lines that a list other than *list_id* still has to buy.

    A line matches on name and unit, the key every door already uses to skip
    what a list carries. A line ticked off elsewhere is bought and is no
    overlap.
    """
    wanted = {(line.name.strip().lower(), line.uom_id): line.name for line in written}
    if not wanted:
        return []
    overlaps: list[ListedElsewhere] = []
    seen: set[tuple[tuple[str, UUID | None], UUID]] = set()
    for other, item in await shopping_lists_api.open_lines_async(
        db, org_id, exclude_list_id=list_id
    ):
        key = (item.name.strip().lower(), item.uom_id)
        if key not in wanted or (key, other.id) in seen:
            continue
        seen.add((key, other.id))
        overlaps.append(
            ListedElsewhere(name=wanted[key], list_id=other.id, list_name=other.name)
        )
    return overlaps
