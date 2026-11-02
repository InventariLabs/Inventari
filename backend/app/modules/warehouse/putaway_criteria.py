"""What a module says about the shelves a putaway rule offers.

The warehouse ranks shelves by what it knows — the operator's rules, the
shelves' capacity, a shelf that holds one product only. A rule only one kind
of warehouse has ("chilled goods go on a cold shelf", "no oxidiser beside a
flammable") belongs to the module that knows it, which registers a criterion
here under its own name, at its import time (like a pre-post check). The
ranking asks every criterion of a module enabled for the organization which
of a rule's shelves may not take the line, and walks the rest.

The criterion governs the rule's own list only. A shelf the worker names on
the line, the serial number's own record and the document's destination are
answers a person gave; a module that must stop those refuses the posting with
a pre-post check instead.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import PutawayCandidateDTO
from app.core.public_api import core_api

#: ``(db, org_id, candidate) -> the shelves that may not take the line``.
#: Asked inside the read or the posting that plans the line; it must not
#: write.
PutawayCriterion = Callable[
    [AsyncSession, UUID, PutawayCandidateDTO], Awaitable[Collection[UUID]]
]

_CRITERIA: dict[str, PutawayCriterion] = {}


def register_putaway_criterion(module: str, criterion: PutawayCriterion) -> None:
    """Claim a say over the putaway ranking for one module.

    Registering twice for the same module replaces the earlier criterion,
    which keeps module reloads (and tests) from accumulating stale entries.
    """
    _CRITERIA[module] = criterion


async def refused_shelves_async(
    db: AsyncSession, org_id: UUID, candidate: PutawayCandidateDTO
) -> set[UUID]:
    """The shelves of ``candidate`` any enabled module's criterion refuses.

    An error propagates: a criterion that cannot answer has not said the
    shelf is fine, and a plan that quietly ignored it would put the goods
    where the module would have stopped them.
    """
    refused: set[UUID] = set()
    if not candidate.location_ids:
        return refused
    for module, criterion in dict(_CRITERIA).items():
        if await core_api.organizations.is_module_enabled_async(db, org_id, module):
            refused.update(await criterion(db, org_id, candidate))
    return refused
