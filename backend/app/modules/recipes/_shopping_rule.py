"""What "buy this" means, said once for both roads onto a shopping list.

Two doors lead from a recipe to a shopping list: the button on a recipe
screen (one or several recipes, merged) and the meal plan's own generation.
Both answer the same question — *what do I still have to buy for this?* —
and they answered it differently: the recipe screen put the ingredient's
**whole** quantity on the list even when the shelf held most of it, and it
never read the organization's "Always at home" exclusions, which the meal
plan had honoured all along. The meal plan, in turn, had no way to say
what it left out.

This module holds the shared half: the exclusions and the arithmetic that
decides how much — what the recipes need together, less what the shelf
covers, so an ingredient gets a line exactly when that is above zero. Each
route keeps its own way of reading the shelf — the recipe screen asks the
availability checker, the meal plan weighs quants — but neither may invent a
second answer to what the rule covers.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from ._name_matching import match_key
from .models import ShoppingExclusion

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ShoppingExclusions:
    """The organization's "Always at home" list, indexed for matching."""

    names: frozenset[str]
    template_ids: frozenset[UUID]

    def excludes(self, name: str, template_id: UUID | None) -> bool:
        """Whether this ingredient is excused by name or by product."""
        return (
            template_id is not None and template_id in self.template_ids
        ) or match_key(name) in self.names


async def load_exclusions(db: AsyncSession, org_id: UUID) -> ShoppingExclusions:
    """Read the exclusions once per request, however many lines follow."""
    rows = (
        await db.execute(
            select(
                ShoppingExclusion.name_normalized, ShoppingExclusion.template_id
            ).where(ShoppingExclusion.organization_id == org_id)
        )
    ).all()
    return ShoppingExclusions(
        names=frozenset(row[0] for row in rows),
        template_ids=frozenset(row[1] for row in rows if row[1] is not None),
    )


def quantity_to_buy(
    required: Decimal,
    available: Decimal,
    *,
    comparable: bool,
) -> Decimal | None:
    """How much of an ingredient a shopping line asks for, or ``None``.

    One formula for every road: what is wanted, less what the shelf can be
    trusted to cover, and the whole requirement when the two numbers cannot
    be put on one scale.
    """
    if not comparable:
        return required
    shortfall = required - available
    return shortfall if shortfall > 0 else None
