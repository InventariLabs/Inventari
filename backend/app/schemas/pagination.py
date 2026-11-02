"""Standard pagination schemas for Inventari API responses."""

from collections.abc import Callable
from typing import Any, Generic, Self, TypeVar

from pydantic import BaseModel

T = TypeVar('T')


class PaginatedResponse(BaseModel, Generic[T]):  # noqa: UP046
    """Offset-based paginated response envelope.

    Usage:
        @router.get('', response_model=PaginatedResponse[MySchema])
        def list_items(limit: int = 50, offset: int = 0, ...) -> PaginatedResponse[MySchema]:
            total = db.scalar(select(func.count(Model.id)))
            items = db.scalars(select(Model).offset(offset).limit(limit)).all()
            return PaginatedResponse(
                items=items,
                total=total,
                limit=limit,
                offset=offset,
                has_more=offset + limit < total,
            )
    """

    items: list[T]
    total: int
    limit: int
    offset: int
    has_more: bool
    #: True when the list stopped counting at ``total``: it holds more rows
    #: than that, and a screen says "more than" ``total``. A list that can grow
    #: with the organization counts only so far (``db_utils.LIST_COUNT_CAP``).
    total_capped: bool = False

    @classmethod
    def from_slice(
        cls,
        items: list[T],
        offset: int,
        limit: int,
        total: int,
        *,
        count_cap: int | None = None,
    ) -> Self:
        """Build a page from an already-fetched slice.

        Centralises the ``has_more=offset + limit < total`` computation
        that every offset-based list endpoint repeats inline.

        ``count_cap`` is the cap the count was taken under
        (``db_utils.paginate_async``): a total past its window is reported as
        the window, with ``total_capped`` set.

        Returns ``Self`` rather than ``PaginatedResponse[T]`` so that
        subclasses (``ItemListResponse``, ``PurchaseOrderListResponse``, …)
        type-check at their own call sites — it already constructed ``cls``
        at runtime, the annotation was just narrower than the behaviour.
        """
        capped = False
        if count_cap:
            from app.core.db_utils import count_window

            window = count_window(offset, limit, count_cap)
            capped = total > window
            total = min(total, window)
        return cls(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
            has_more=capped or offset + limit < total,
            total_capped=capped,
        )

    @classmethod
    def from_full_list(cls, items: list[T], offset: int, limit: int) -> Self:
        """Build a page from a list the caller already holds in memory.

        A list that stays small — a settings table, a picker, a catalogue an
        organization will not grow past a few thousand rows — is read whole by
        its service and sliced here, so the endpoint still answers with the
        documented envelope. A list that can grow does not use this: it pages
        in the database (``db_utils.paginate_async`` for offset, a keyset read
        for a feed), because reading it whole is the cost this envelope exists
        to avoid. See ``docs/subsystems/PAGINATION.md``.
        """
        return cls.from_slice(items[offset : offset + limit], offset, limit, len(items))


class KeysetPaginatedResponse[T](PaginatedResponse[T]):
    """A page of a list that is paged by the last row seen, with its count.

    Same envelope as ``PaginatedResponse`` — ``total``, ``offset`` and
    ``has_more`` keep meaning what they meant, so a screen written for offset
    pages reads it unchanged — plus the cursor for the page that follows. The
    cursor carries the count the first page took and the number of rows served
    so far, which is how a deep page can say "101-200 of 5,000" without
    counting 5,000 rows again.
    """

    next_cursor: str | None = None

    @classmethod
    def from_keyset(
        cls,
        items: list[T],
        offset: int,
        limit: int,
        total: int,
        next_cursor: str | None,
        *,
        total_capped: bool = False,
    ) -> Self:
        """Build a page of a keyset-paginated list.

        ``offset`` is how many rows came before this page and ``total`` is the
        count the first page took; both ride in the cursor, and so does
        ``total_capped`` when that count stopped at the cap. ``has_more`` is
        whether a next page exists, which the fetch of one extra row settled.
        """
        return cls(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
            has_more=next_cursor is not None,
            next_cursor=next_cursor,
            total_capped=total_capped,
        )


class CursorPaginatedResponse(BaseModel, Generic[T]):  # noqa: UP046
    """Cursor-based paginated response for large datasets.

    Use ``id`` or ``created_at`` as cursor column; encode cursor as base64.
    Suitable for endpoints with high-frequency inserts (item history, webhook logs).
    """

    items: list[T]
    next_cursor: str | None
    has_more: bool

    @classmethod
    def from_cursor_page(
        cls,
        items: list[T],
        limit: int,
        encode_cursor: Callable[[T], str],
        transform: Callable[[T], Any] | None = None,
    ) -> 'CursorPaginatedResponse[Any]':
        """Build a page from a ``limit + 1`` cursor fetch.

        Matches the inline pattern used by cursor-paginated endpoints
        (item history, webhook deliveries): the fetch asks for one extra
        row so ``has_more`` is ``len(items) > limit``, the page is the
        first ``limit`` rows, and the next cursor is encoded from the
        last row of the page. ``transform`` optionally maps raw rows to
        response schemas before slicing.
        """
        has_more = len(items) > limit
        page = items[:limit]
        next_cursor = encode_cursor(page[-1]) if has_more and page else None
        payload = [transform(item) for item in page] if transform else page
        return cls(items=payload, next_cursor=next_cursor, has_more=has_more)
