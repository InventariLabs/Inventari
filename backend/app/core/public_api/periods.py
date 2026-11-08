"""Public Core API for inventory period guards.

Delegates to the period-guard registry (:mod:`app.core.period_guard`) — the
``warehouse`` module registers its implementation at startup, which keeps
Core free of any ``app.modules.*`` import. When the documents
module is absent, the guard is a no-op.

Item-side mutations
(consume/discard/move/update_quantity/scan/bulk/stock_take/recipe-pick)
were silently bypassing the inventory period lock. Documents guarded
their workflow transitions via inline checks, but every other stock-
mutating path ignored the lock. ``check_not_closed_async`` makes the
guard available to all modules via the standard Core facade.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    PeriodClosedError,  # re-exported for convenience
)
from app.core.period_guard import check_period_not_closed
from app.core.public_api._access import reads


class CorePeriodsAPI:
    """Public Core API namespace for inventory period guards."""

    @reads
    async def check_not_closed_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        doc_date: date,
    ) -> None:
        """Raise ``PeriodClosedError`` if the given date falls in a closed period.

        ``PeriodClosedError`` (defined in ``app.core.exceptions``) is a
        subclass of ``ValueError``. Routers must catch it explicitly and map
        to ``HTTP 409 Conflict`` with code ``PERIOD_CLOSED``. For real-time
        item mutations call with ``date.today()``; for document-scoped calls
        use the document's scheduled_date.
        """
        await check_period_not_closed(db, organization_id, doc_date)


__all__ = ['CorePeriodsAPI', 'PeriodClosedError']
