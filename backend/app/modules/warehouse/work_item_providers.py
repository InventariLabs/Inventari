"""Who may add tasks to To do.

The warehouse module reads its own documents; every other source of work
registers here instead — a purchase order that expects goods, a production run,
a count that has fallen due, and whatever a customer-specific module needs
("check the delivery certificate"). A provider is registered under the name of
the module that owns it, at that module's import time (like an approvals target
summary provider), and is called only while that module is enabled for the
organization, so a module that is switched off takes its tasks with it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import WorkItemDTO, WorkItemQueryDTO

#: ``(db, org_id, query) -> (tasks due by query.date_to, how many there are in all)``.
#: The tasks come soonest first and at most ``query.limit``; the count covers
#: every task the module has, so a longer queue says so.
WorkItemProvider = Callable[
    [AsyncSession, UUID, WorkItemQueryDTO],
    Awaitable[tuple[list[WorkItemDTO], int]],
]

_PROVIDERS: dict[str, WorkItemProvider] = {}


def register_work_item_provider(module: str, provider: WorkItemProvider) -> None:
    """Claim the tasks of one module.

    Registering twice for the same module replaces the earlier provider, which
    keeps module reloads (and tests) from accumulating stale entries.
    """
    _PROVIDERS[module] = provider


def work_item_providers() -> dict[str, WorkItemProvider]:
    """The registered providers, by the module that owns each."""
    return dict(_PROVIDERS)
