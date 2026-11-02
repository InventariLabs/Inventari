"""Cursor encoding/decoding helpers for cursor-based pagination."""

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.core.exceptions import ValidationException, catalogue_refusal


def encode_cursor(item_id: UUID, created_at: datetime) -> str:
    """Encode a cursor from an item's id and created_at timestamp."""
    payload = {'id': str(item_id), 'ts': created_at.isoformat()}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(cursor: str) -> tuple[UUID, datetime]:
    """Decode a cursor string back to (id, created_at).

    Raises HTTP 400 if the cursor is malformed or tampered with.
    """
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return UUID(payload['id']), datetime.fromisoformat(payload['ts'])
    except (ValueError, TypeError, KeyError) as exc:
        raise catalogue_refusal('pagination_cursor_invalid') from exc


@dataclass(frozen=True)
class KeysetCursor:
    """Where a keyset-paginated list stopped, and what the first page learned.

    ``sort_value`` and ``row_id`` are the last row the reader was given, which
    is the whole of what the next page needs to start below it. ``total`` is
    the size of the full answer, counted once on the first page and carried
    from there, so no later page pays for a count and the figure the reader
    sees does not move while they page. ``offset`` is how many rows came
    before the next page, which lets the screen say "101-200 of 5,000" without
    asking. ``total_capped`` says the first page stopped counting at
    ``total`` (``db_utils.LIST_COUNT_CAP``): the list holds more.
    """

    sort_value: datetime
    row_id: UUID
    total: int | None = None
    offset: int = 0
    total_capped: bool = False


def encode_keyset_cursor(
    sort_value: datetime,
    row_id: UUID,
    *,
    total: int | None = None,
    offset: int = 0,
    total_capped: bool = False,
) -> str:
    """Encode the position after one row, with the count and offset to carry."""
    payload: dict[str, str | int] = {
        'id': str(row_id),
        'ts': sort_value.isoformat(),
        'o': offset,
    }
    if total is not None:
        payload['n'] = total
    if total_capped:
        payload['c'] = 1
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _invalid_keyset_cursor() -> ValidationException:
    return catalogue_refusal('pagination_cursor_invalid', field='cursor')


def decode_keyset_cursor(cursor: str) -> KeysetCursor:
    """Decode a keyset cursor; a 400 when it is malformed or altered.

    A cursor holds no authority: the query that reads it is still scoped to
    the caller's organization and filters. The worst a forged one can do is
    show its sender a wrong count.
    """
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        sort_value = datetime.fromisoformat(payload['ts'])
        row_id = UUID(payload['id'])
        total = payload.get('n')
        offset = payload.get('o', 0)
        total_capped = payload.get('c') == 1
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise _invalid_keyset_cursor() from exc
    if (total is not None and not _is_count(total)) or not _is_count(offset):
        raise _invalid_keyset_cursor()
    if sort_value.tzinfo is None:
        sort_value = sort_value.replace(tzinfo=UTC)
    return KeysetCursor(sort_value, row_id, total, offset, total_capped)
