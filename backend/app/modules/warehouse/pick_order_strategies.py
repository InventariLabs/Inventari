"""How the warehouse is walked — the picking order.

The warehouse module owns the default walk: the numbers on the locations,
then the code, then the name. A warehouse that picks by another rule — a
zone first, a route a module computes from its own tables — registers a
strategy here under its own name (at that module's import time, like a To do
provider or a pre-post check) and the organization chooses one in the
warehouse settings. The default is registered the same way and is what the
walk uses when nothing is chosen, or when the chosen strategy's module is
switched off for the organization.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import PickOrderLineDTO
from app.core.public_api import core_api

#: ``(db, org_id, lines) -> the same lines in pick order``. The lines carry
#: each pick line's product, quantity, shelf and the shelf's path; returning
#: them reordered is the walk. The strategy is asked inside the session
#: start's transaction and must not commit.
PickOrderStrategy = Callable[
    [AsyncSession, UUID, list[PickOrderLineDTO]],
    Awaitable[Sequence[PickOrderLineDTO]],
]

#: The walk the warehouse does when nobody has chosen: the order the
#: locations are numbered.
DEFAULT_PICK_ORDER_STRATEGY = 'location_sequence'

#: A level of the path where a location carries no number: after every number.
_UNNUMBERED = (True, 0)

_STRATEGIES: dict[str, tuple[str, PickOrderStrategy]] = {}


def register_pick_order_strategy(
    module: str, name: str, strategy: PickOrderStrategy
) -> None:
    """Claim a way of walking the warehouse under one name.

    The name is the strategy's identity the organization's choice names —
    it is offered in the warehouse settings under
    ``<module>:pickOrderStrategies.<name>`` from *module*'s catalogue.
    Registering the same name replaces the earlier entry, which keeps module
    reloads (and tests) from accumulating stale entries.
    """
    _STRATEGIES[name] = (module, strategy)


def pick_order_strategies() -> dict[str, tuple[str, PickOrderStrategy]]:
    """The registered strategies by name, each beside the module that owns it."""
    return dict(_STRATEGIES)


def strategy_label_key(module: str, name: str) -> str:
    """The catalogue key the warehouse settings name this strategy by.

    The full form the module settings' ``title_key`` takes: the screen
    resolves it against the owning module's translation catalogue and falls
    back to the bare name when the catalogue has none.
    """
    return f'{module}:pickOrderStrategies.{name}'


async def resolve_pick_order_strategy_async(
    db: AsyncSession, org_id: UUID
) -> PickOrderStrategy:
    """The strategy this organization walks by — the default, never a refusal.

    Nothing chosen, a name nothing registered, and a strategy whose module is
    switched off for the organization all answer the default: the walk runs
    the way it always did. A module turned off after its strategy was chosen
    costs the organization its walk, not a session that will not start.
    """
    from .document_profile_service import get_profile

    profile = await get_profile(db, org_id)
    name = profile.pick_order_strategy if profile is not None else None
    entry = _STRATEGIES.get(name) if name else None
    if entry is not None:
        module, strategy = entry
        if await core_api.organizations.is_module_enabled_async(db, org_id, module):
            return strategy
    return _STRATEGIES[DEFAULT_PICK_ORDER_STRATEGY][1]


async def _order_by_location_sequence(
    db: AsyncSession, org_id: UUID, lines: list[PickOrderLineDTO]
) -> Sequence[PickOrderLineDTO]:
    """Order the lines the way the warehouse is walked.

    A line's place on the walk is the numbers of the location it is taken
    from — each ancestor's, then its own — so a whole aisle comes before the
    next one and the shelves inside it follow their own numbers. A level
    without a number comes after the numbered ones; equal paths fall back to
    the code and then the name, which is the whole order when nobody numbered
    anything. Lines with no location at all come last.
    """
    depth = max((len(line.location_path) for line in lines), default=0)

    def walk_key(line: PickOrderLineDTO) -> tuple[Any, ...]:
        path = [
            (step.sequence is None, step.sequence or 0) for step in line.location_path
        ] + [_UNNUMBERED] * (depth - len(line.location_path))
        own = line.location_path[-1] if line.location_path else None
        return (
            own is None,
            path,
            (own.short_code or '') if own else '',
            (own.name or '') if own else '',
            line.bin_location or '',
        )

    return sorted(lines, key=walk_key)


register_pick_order_strategy(
    'warehouse', DEFAULT_PICK_ORDER_STRATEGY, _order_by_location_sequence
)
