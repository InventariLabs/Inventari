"""One definition of item expiry, shared by every count that reports it.

The rule is written once here because writing it twice is how the overview
tile and the list behind it came to disagree by one item.

The date an item is judged by is its *effective* expiry: the batch's date, or
the use-by its owner gave when opening it, whichever is earlier (see
``Item.effective_expiry_date``). A record with no use-by is judged by the
batch's date alone, as it always was.

An item whose expiry date *is* today has not expired: "best before 15.08"
means 15.08 is still fine. It belongs in the expiring-soon bucket instead, so
it never falls out of both.

Callers pass *today* — the organization's own day, resolved by whichever
caller has the org and the database in scope. The ``date.today()`` fallback
is the server's clock and exists only for callers with no organization to
ask; every real entry point passes the org's day.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item

DEFAULT_EXPIRING_SOON_DAYS = 7


def is_expired(today: date | None = None) -> ColumnElement[bool]:
    """Item is past its expiry date. Today's date does not count as expired."""
    today = today or date.today()
    expiry = Item.effective_expiry_date
    return and_(expiry.isnot(None), expiry < today)


def is_expiring_soon(
    today: date | None = None, days: int = DEFAULT_EXPIRING_SOON_DAYS
) -> ColumnElement[bool]:
    """Item expires within the horizon, today included, and is not expired."""
    today = today or date.today()
    expiry = Item.effective_expiry_date
    return and_(
        expiry.isnot(None),
        expiry >= today,
        expiry <= today + timedelta(days=days),
    )


async def expiry_today_async(db: AsyncSession, organization_id: UUID | None) -> date:
    """The day this organization's expiry horizon is measured from.

    Every caller of the two predicates above needs it and each used to
    resolve it inline. The fallback to the server's clock is for the
    callers that have no organization to ask.
    """
    if organization_id is None:
        return date.today()
    from app.services.analytics._common import org_today_async

    return await org_today_async(db, organization_id)
