"""Reading the page that follows a row, in two index seeks.

A list sorted ``moment DESC, id`` has two kinds of rows below the one a reader
saw last: the rest of the group that shares its instant (the larger ids), and
everything older. As one condition — ``moment <= seen AND (moment < seen OR id >
seen_id)`` — the database can seek to the instant but then reads the whole group
that shares it to throw away the ids it has already shown. A group is not
bounded by the page: a bulk import or a stocktake closed in one go writes
thousands of rows at one instant, and a page that starts inside it then cost
the size of the group.

Asked as two ranges, each is one seek on an index ordered by ``(moment, id)``:
the tail of the group (``moment = seen AND id > seen_id``, read in id order) and
then, only if the page is not full yet, the older rows. The cost of a page is
the page.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, SQLColumnExpression


async def read_page_after[T](
    read: Callable[
        [Sequence[ColumnElement[bool]], Sequence[Any], int], Awaitable[list[T]]
    ],
    *,
    moment: SQLColumnExpression[datetime],
    row_id: SQLColumnExpression[UUID],
    after: tuple[datetime, UUID],
    limit: int,
) -> list[T]:
    """The *limit* rows below ``after`` in ``moment DESC, id`` order.

    *read* runs the list's statement — its own filters and joins — with the
    conditions, the ``ORDER BY`` terms and the limit it is handed. *moment* is
    the expression the list sorts by and *row_id* its tiebreak; both must be
    what the index is on, or the seeks are not seeks.
    """
    seen_at, seen_id = after
    tied = await read([moment == seen_at, row_id > seen_id], [row_id], limit)
    if len(tied) >= limit:
        return tied
    older = await read([moment < seen_at], [moment.desc(), row_id], limit - len(tied))
    return tied + older
