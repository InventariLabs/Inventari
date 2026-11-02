"""What "buy this" means, said once for both roads onto a shopping list.

Two doors lead from a recipe to a shopping list: the button on a recipe
screen (one or several recipes, merged) and the meal plan's own generation.
Both answer the same question — *what do I still have to buy for this?* —
and they answered it differently: the recipe screen put the ingredient's
**whole** quantity on the list even when the shelf held most of it, and it
never read the organization's "Always at home" exclusions, which the meal
plan had honoured all along. The meal plan, in turn, had no way to say
what it left out.

This module holds the shared half: the exclusions, the predicate that
decides whether an ingredient gets a line at all, and the arithmetic that
decides how much. Each route keeps its own way of reading the shelf — the
recipe screen asks the availability checker, the meal plan weighs quants —
but neither may invent a second answer to what the rule covers.
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


def needs_buying(status: str, comparable: bool) -> bool:
    """Whether an ingredient's availability leaves it on the list.

    "Not comparable" is not "nothing missing": with the recipe's measure and
    the shelf's on different scales, nobody can say the stock covers it.
    "Similar" — goods found by the ingredient's name rather than a link —
    covers it like any other stock, the way the meal plan has always
    deducted it and the recipe screen's counters count it as held. Buying
    it in full put rice on the list under a counter reading "Missing 1",
    and bought more the more of it the shelf held: 150 g of a name-matched
    200 g was short by 50 g, while a whole kilo bought all 200 g. The recipe
    screen's button reads this same predicate, so the door and the list
    behind it cannot disagree.
    """
    return not comparable or status in (
        'missing',
        'insufficient',
        'incomparable',
        'unknown',
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
