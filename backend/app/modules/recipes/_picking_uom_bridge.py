"""Put the recipe's measure and the shelf's measure on one scale, or refuse.

The recipe asks in its own unit; the shelf is counted in the item's. Picking
decrements the item, so the amount it takes must be expressed in the item's
unit — and when nothing records how the two units relate, there is no honest
number to take. This module answers with ``None`` in that case instead of
comparing raw digits, which is what let "500 g" swallow a whole piece.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.public_api import core_api

from ._uom_helpers import convert_qty_for_template

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.contracts import ItemDTO, UomDTO

    from .models import RecipeIngredient


class UnitBridge:
    """What the recipe asks for, expressed against one item on the shelf."""

    def __init__(
        self,
        needed_in_item_uom: Decimal | None,
        required_uom_symbol: str | None,
        available_uom_symbol: str | None,
        required_uom: UomDTO | None = None,
    ) -> None:
        self.needed_in_item_uom = needed_in_item_uom
        self.required_uom_symbol = required_uom_symbol
        self.available_uom_symbol = available_uom_symbol
        #: The recipe's own unit, carried through so the caller can restate
        #: progress in it without loading the unit table a second time.
        self.required_uom = required_uom

    @property
    def comparable(self) -> bool:
        return self.needed_in_item_uom is not None


async def bridge_needed_quantity(
    db: AsyncSession,
    org_id: UUID,
    ingredient: RecipeIngredient,
    scanned_item: ItemDTO,
    needed: Decimal,
    uoms: dict[UUID, UomDTO] | None = None,
) -> UnitBridge:
    """Express *needed* (the ingredient's unit) in the scanned item's unit.

    Falls back to a straight pass-through only when neither side names a
    unit at all — two bare numbers were always compared as bare numbers, and
    changing that would block picking for every product that predates units.
    """
    if uoms is None:
        uoms = {
            uom.id: uom for uom in await core_api.uoms.list_for_org_async(db, org_id)
        }
    source = uoms.get(ingredient.uom_id) if ingredient.uom_id else None
    target = uoms.get(scanned_item.uom_id) if scanned_item.uom_id else None

    template = None
    if scanned_item.template_id:
        templates = await core_api.product_templates.get_many_async(
            db, org_id, [scanned_item.template_id]
        )
        template = templates.get(scanned_item.template_id)

    converted = convert_qty_for_template(needed, source, target, template, uoms)
    return UnitBridge(
        # The item unit's own step deliberately does not apply here. This is
        # what comes off the shelf, and an opened package holds a fraction of
        # a piece: 500 g taken from a piece that weighs a kilogram is half of
        # it, and rounding that up to a whole piece would take twice what the
        # recipe asked for. Only the quantity columns' scale applies — that
        # is what ``uom=None`` asks for. The unit's step governs what is asked
        # of a person, not what a conversion reads off stock.
        needed_in_item_uom=core_api.uoms.quantize(converted, None)
        if converted is not None
        else None,
        required_uom_symbol=source.symbol if source else None,
        available_uom_symbol=target.symbol if target else scanned_item.uom_symbol,
        required_uom=source,
    )
