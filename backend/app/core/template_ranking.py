"""Template-ranking registry — inversion of the Core → recipes dependency.

Core can list an organization's product templates on its own. What it cannot
do is order them by how often recipes use them: the usage count lives in the
recipes module's ``RecipeIngredient`` table.

Before this registry Core imported ``recipes_api`` to get that ordering, which
also closed a loop — the only caller is ``core_api.product_templates``, used by
the recipes template matcher, so recipes called Core which called recipes.

Now recipes registers its ranker and Core asks through here.

Absence degrades rather than fails: with no ranker the caller falls back to the
plain alphabetical listing. The result is less useful for prompt building but
entirely valid, which is the right trade for a feature that only sharpens an
ordering.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

TemplateRankerFn = Callable[['AsyncSession', 'UUID', int], Awaitable[list[Any]]]

_ranker: TemplateRankerFn | None = None


def register_template_ranker(fn: TemplateRankerFn) -> None:
    """Register the usage-based ranker (called by the owning module)."""
    global _ranker
    _ranker = fn


def clear_template_ranker() -> None:
    """Reset the registry — test isolation only."""
    global _ranker
    _ranker = None


async def rank_templates_by_usage(
    db: AsyncSession, org_id: UUID, limit: int = 200
) -> list[Any] | None:
    """Templates ordered by recipe usage, or ``None`` when no ranker is registered."""
    if _ranker is None:
        return None
    return await _ranker(db, org_id, limit)
