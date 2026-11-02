"""FEFO/sort/serialization helpers for recipe ingredients and items.

Kept private to the recipes module — not part of the public facade.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UomDTO
from app.core.public_api import core_api

from ._picking_fefo import StockedItem, expiry_of, is_past
from .models import Recipe
from .schemas import BestItemSchema


class ShelfItem(StockedItem, Protocol):
    """A stocked item with an identity — what the availability payload shows."""

    @property
    def id(self) -> UUID: ...


def _round_shopping_qty(qty: Decimal | float | int, uom: UomDTO | None) -> Decimal:
    """Round a shopping-list quantity up to the unit's own step, never under.

    The unit's ``rounding`` is the answer — 1 for a piece, 0.5 for goods
    sold in halves, 0.001 for a gram — and the whole-unit rule baked in
    here read as that answer for pieces and lied everywhere else: half a
    kilo of flour became "1 kg". ROUND_CEILING keeps the never-under-buy
    property (needing part of a step is needing the step), which also
    covers the old ``max(1)`` on countable units; for measured units the
    floor is the unit's own step, deliberately not one whole unit. A line
    without a unit falls to the quantity column's own scale, the same
    fallback ``quantity_step`` applies everywhere.
    """
    if isinstance(qty, float):
        qty = Decimal(str(qty))
    elif isinstance(qty, int):
        qty = Decimal(qty)
    return core_api.uoms.round_up(qty, uom)


def resolve_servings_request(
    recipe_servings: int,
    servings: int | None,
    scale: Decimal | None,
) -> int | Decimal:
    """The serving count a request asks for, with the scale taking precedence.

    ``scale`` states the multiplier directly: multiplied out it can be
    fractional, and the quantity math carries it exactly. ``servings``
    keeps its own semantics untouched — 0 and None both mean the recipe's
    own count.
    """
    if scale is not None:
        return Decimal(recipe_servings) * scale
    return servings if servings else recipe_servings


def display_servings(servings: int | Decimal) -> int:
    """The whole number a possibly fractional serving count reports as.

    Quantity math keeps the exact multiplier; the int serving fields in
    responses round the fraction, so a client reading them keeps getting a
    whole number. (Carrying the exact factor out to clients is its own
    later change.)
    """
    return int(Decimal(servings).to_integral_value(rounding=ROUND_HALF_UP))


def _item_to_schema(
    item: ShelfItem, fefo_warning: int | None, *, today: date
) -> BestItemSchema:
    """Serialize one item for the availability payload.

    The unit is the *item's* own, not the recipe's. This row reports what
    sits on the shelf, and labelling seven cans as "7 g" because the recipe
    happens to ask for grams is how the mismatch stayed invisible. Whether
    it is past its date travels along, so the row can say so instead of
    reading the date as a warning about the future.
    """
    return BestItemSchema(
        item_id=item.id,
        available_quantity=float(item.quantity or 0),
        uom_symbol=_uom_symbol(item),
        expiry_date=str(expiry_of(item)) if expiry_of(item) else None,
        location=_location_name(item),
        fefo_days_left=fefo_warning,
        expired=is_past(item, today),
    )


def _uom_symbol(item: ShelfItem) -> str | None:
    """Return the unit symbol for either an ORM row or an ItemDTO."""
    symbol = getattr(item, 'uom_symbol', None)
    if isinstance(symbol, str):
        return symbol
    uom = getattr(item, 'uom', None)
    symbol = getattr(uom, 'symbol', None) if uom else None
    return symbol if isinstance(symbol, str) else None


def _location_name(item: ShelfItem) -> str | None:
    """Return the storage location name for either an ORM row or an ItemDTO."""
    name = getattr(item, 'location_name', None)
    if isinstance(name, str):
        return name
    storage = getattr(item, 'storage_location', None)
    name = getattr(storage, 'name', None) if storage else None
    return name if isinstance(name, str) else None


async def set_recipe_image_url(
    db: AsyncSession, recipe: Recipe, image_url: str | None
) -> Recipe:
    recipe.image_url = image_url
    await db.flush()
    await db.refresh(recipe)
    return recipe
