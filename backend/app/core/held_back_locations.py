"""Held-back locations — places goods wait in, not live in.

Core knows a location only as a place that holds stock. A module can set some
of them apart: the warehouse keeps a receiving area where deliveries wait to
be put away, and a quarantine location where goods held for quality are kept
out of picking. A flow that means to *keep* goods somewhere (what a production
run makes, stock added by hand) must not offer such a place as a shelf, and
Core must not learn the names of the module's settings to say which they are.

The module *registers* a provider here at startup, the way the warehouse
registers its period guard; the location list and the services that take a
destination ask :func:`held_back_locations_async`. A provider answers for
every location below the one it names — a zone is held back with everything
inside it — and names the reason as a short code (``receiving``,
``quarantine``) the caller turns into a sentence.

Graceful degradation: with no provider registered (the module absent or
rejected) nothing is held back, so no flow is refused for a setting that does
not exist.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

HeldBackProvider = Callable[['AsyncSession', 'UUID'], Awaitable['dict[UUID, str]']]

_providers: dict[str, HeldBackProvider] = {}


def register_held_back_locations(module: str, provider: HeldBackProvider) -> None:
    """Register what one module holds back (called by the owning module)."""
    _providers[module] = provider


async def held_back_locations_async(
    db: AsyncSession, organization_id: UUID
) -> dict[UUID, str]:
    """Every location goods are not kept in, with the reason each is held back.

    Empty when no module registered a provider. When two providers name the
    same location, the first one registered keeps it.
    """
    held: dict[UUID, str] = {}
    for provider in list(_providers.values()):
        for location_id, reason in (await provider(db, organization_id)).items():
            held.setdefault(location_id, reason)
    return held
