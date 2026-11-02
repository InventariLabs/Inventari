"""Who can describe the thing an approval request points at.

The approvals queue shows a card per request. Filling that card needs
knowledge only the requesting module has — a document's number and value, a
purchase order's supplier and total — and the enrichment used to reach for
``warehouse_api`` directly, skipping every other target type in silence. That
made the engine the keeper of a list of its own consumers, the opposite of the
cross-module contract, and it left purchase orders rendering as eight
characters of a UUID.

So the direction is reversed: a module that requests approval registers a
provider for its own target type at import time, and the engine asks whoever
is registered. A target type with no provider degrades exactly as before —
``target_summary`` stays ``None`` and the card falls back to the identifier.
"""

from collections.abc import Awaitable, Callable, Collection, Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

TargetSummaryProvider = Callable[
    [AsyncSession, UUID, list[UUID]], Awaitable[Mapping[UUID, Any]]
]

_PROVIDERS: dict[str, TargetSummaryProvider] = {}

#: ``(db, org_id, text) -> ids of the targets whose summary matches the text``.
TargetSearchProvider = Callable[[AsyncSession, UUID, str], Awaitable[Collection[UUID]]]

_SEARCH_PROVIDERS: dict[str, TargetSearchProvider] = {}


def register_target_summary_provider(
    target_type: str, provider: TargetSummaryProvider
) -> None:
    """Claim the summaries for one target type.

    Registering twice for the same type replaces the earlier provider, which
    keeps module reloads (and tests) from accumulating stale entries.
    """
    _PROVIDERS[target_type] = provider


def get_target_summary_provider(target_type: str) -> TargetSummaryProvider | None:
    """The provider for a target type, or ``None`` when nobody claimed it."""
    return _PROVIDERS.get(target_type)


def register_target_search_provider(
    target_type: str, provider: TargetSearchProvider
) -> None:
    """Let the queue's search find a target by what its card shows.

    The card names an asset or an order the way its module describes it, and
    the search box knew only identifiers: searching for the name on the card
    found nothing while the request waited. The module that describes its
    target answers the search too. Registering twice replaces the earlier one.
    """
    _SEARCH_PROVIDERS[target_type] = provider


def target_search_providers() -> Mapping[str, TargetSearchProvider]:
    """Every registered search provider, by target type."""
    return dict(_SEARCH_PROVIDERS)
