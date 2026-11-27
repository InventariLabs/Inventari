"""What a module brings in a move from another program.

A move reads a file that holds more than the core's records: Grocy's holds
shopping lists, recipes and chores beside its products and stock. The core
files its own part, then hands the same rows — with the products and units it
matched — to every module that registered for the source and is switched on
for the organization. A module answers with one sentence for the summary, in
the reader's language, and names the kind of record it takes over, so the
summary stops listing that kind among what stays behind — once its part has
run; a kind whose part failed stays listed, marked as failed.

A contributor runs in the move's transaction, in a savepoint of its own: one
that fails is logged, its writes roll back, and the move goes on without it.
The core never imports a module (architecture lint); a module registers here
when it is imported, as export enrichers do.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.contracts import UserContextDTO

logger = get_logger(__name__)


@dataclass(frozen=True)
class MoveMatches:
    """What the core's part of a move made of the source's own ids."""

    #: The source's product id, as text → the product it became or matched.
    products: dict[str, UUID]
    #: The source's unit id → the unit here it was matched to.
    units: dict[int, UUID]


#: Brings a module's part of a move: given the session, the mover, the
#: source's rows as the core read them and the core's matches, writes what
#: the module keeps and answers the summary's sentence, or ``None`` when the
#: file held nothing for it.
BringFn = Callable[
    ['AsyncSession', 'UserContextDTO', Any, MoveMatches], Awaitable[str | None]
]


@dataclass(frozen=True)
class MoveContributor:
    module: str
    #: The kind of record the summary would otherwise list as staying behind
    #: (``shopping_list_entries``); while the module is on, it comes across.
    takes: str
    bring: BringFn


_contributors: dict[str, list[MoveContributor]] = {}


def register_move_contributor(source: str, contributor: MoveContributor) -> None:
    """Register a module's part of moves from *source* (called at import time).

    A second registration of the same module for the same source replaces the
    first, so a module imported twice is not asked twice.
    """
    others = [
        c for c in _contributors.get(source, []) if c.module != contributor.module
    ]
    _contributors[source] = [*others, contributor]


def contributors_for(
    source: str, enabled_modules: Iterable[str]
) -> list[MoveContributor]:
    """The contributors to a move from *source* whose module is switched on."""
    enabled = set(enabled_modules)
    return [c for c in _contributors.get(source, []) if c.module in enabled]


@dataclass(frozen=True)
class MoveContribution:
    module: str
    sentence: str


@dataclass(frozen=True)
class MoveOutcome:
    #: The sentences of the parts that had something to say.
    brought: list[MoveContribution]
    #: The kinds (``MoveContributor.takes``) whose module's part failed.
    failed: set[str]


async def bring_async(
    source: str,
    db: AsyncSession,
    user: UserContextDTO,
    rows: Any,
    matches: MoveMatches,
    enabled_modules: Iterable[str],
) -> MoveOutcome:
    """Every switched-on module's part of the move, each in a savepoint."""
    brought: list[MoveContribution] = []
    failed: set[str] = set()
    for contributor in contributors_for(source, enabled_modules):
        try:
            async with db.begin_nested():
                sentence = await contributor.bring(db, user, rows, matches)
        except Exception:  # a module's part must not undo the core's
            logger.exception(
                'Move contributor %s failed for a %s move by %s',
                contributor.module,
                source,
                user.id,
            )
            failed.add(contributor.takes)
            continue
        if sentence:
            brought.append(MoveContribution(contributor.module, sentence))
    return MoveOutcome(brought, failed)
