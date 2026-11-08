"""Period-guard registry — inversion of the Core → warehouse dependency.

Inventory period locks are owned by the ``warehouse`` module (model, table,
close/reopen workflow). Core stock-mutating paths still need the guard, but
Core must never import a feature module. Instead of Core importing
``warehouse.inventory_period_service``, the warehouse module *registers* its
guard implementation here at startup, and Core calls it through this
registry.

Graceful degradation: when no guard is registered (warehouse module absent
or rejected), :func:`check_period_not_closed` is a no-op — period locking is
a warehouse feature, so without the module there is nothing to enforce.

Once registered, the guard answers for every organization, including one that
has switched the module off since: closing a month is an accounting act, and
only reopening it undoes it. Switching the module off does not reopen a closed
month behind the accountant's back; the organization switches the module on
again to reopen it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

PeriodGuardFn = Callable[['AsyncSession', 'UUID', 'date'], Awaitable[None]]

_guard: PeriodGuardFn | None = None


def register_period_guard(fn: PeriodGuardFn) -> None:
    """Register the period-guard implementation (called by the owning module)."""
    global _guard
    _guard = fn


def clear_period_guard() -> None:
    """Reset the registry — test isolation only."""
    global _guard
    _guard = None


async def check_period_not_closed(
    db: AsyncSession, organization_id: UUID, doc_date: date
) -> None:
    """Invoke the registered period guard, if any.

    Raises ``PeriodClosedError`` (from ``app.core.exceptions``) when the
    registered guard rejects *doc_date*. No-op when unregistered.
    """
    if _guard is None:
        return
    await _guard(db, organization_id, doc_date)
