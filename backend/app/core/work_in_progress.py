"""What the goods a feature is still making are worth, between start and finish.

A production run that is started takes its ingredients off the records and
their cost layers at once, and puts nothing back until it finishes. Between
the two the organization still owns what those ingredients cost, and a stock
value that dropped by it on the day the run started — and returned on the
day it ended — would misstate the warehouse for exactly as long as the batch
matures. The feature that holds such work registers a reader here; Core adds
what it answers to the value of the stock, on the dashboard and on a past
date, without knowing which feature it came from.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

#: ``(db, organization_id, as_of)`` -> the value of the work in progress at
#: *as_of* (now when ``None``), in the organization's money.
WorkInProgressProvider = Callable[
    [AsyncSession, UUID, datetime | None], Awaitable[Decimal]
]

_providers: list[WorkInProgressProvider] = []


def register_work_in_progress_provider(provider: WorkInProgressProvider) -> None:
    """Register a feature's reader of the value it holds in work in progress."""
    if provider not in _providers:
        _providers.append(provider)


async def work_in_progress_value_async(
    db: AsyncSession, organization_id: UUID, as_of: datetime | None = None
) -> Decimal:
    """The value of everything registered features hold in work in progress."""
    total = Decimal('0')
    for provider in _providers:
        total += await provider(db, organization_id, as_of)
    return total
