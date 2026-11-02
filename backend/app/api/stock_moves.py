"""GET /api/v1/stock-moves — the organization's movement ledger.

``StockMove`` is written by every path that changes physical stock, and one
of those paths is Core's own (``services/items/_stock_quant.py``). The only
reader used to be a route the warehouse module registered behind
``require_module('warehouse')``, so an organization that ran a warehouse
without that module wrote to a ledger it could not open.

The ledger is therefore served from Core. It answers for every organization:
with rows where there are rows and with an empty page where nothing was
ever recorded — an empty ledger is an answer, and a 404 would blame the
caller for a module they never asked for.
Whether the *interface* offers a way in is a separate question, decided by
the modules the organization installed.

Nobody comes to a ledger asking for everything, so every question a warehouse
actually asks is a filter: which product, which place (and everything below
it), which batch, which document, which person, which week, and which way the
goods went. Read-only by design: movements are recorded by the services that
move stock, never posted through the API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import StockMoveRowDTO, SystemPermission, UserContextDTO
from app.core.cursor import decode_keyset_cursor, encode_keyset_cursor
from app.core.db_utils import LIST_COUNT_CAP, count_window
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import catalogue_refusal
from app.core.public_api import core_api
from app.core.xlsx_export import to_xlsx_response
from app.schemas.pagination import KeysetPaginatedResponse
from app.services.analytics._common import org_timezone_async
from app.services.stock_moves_service import (
    DIRECTION_IN,
    DIRECTION_INTERNAL,
    DIRECTION_OUT,
    rows_to_export_frame,
)

router = APIRouter()

_DIRECTIONS = f'{DIRECTION_IN}|{DIRECTION_OUT}|{DIRECTION_INTERNAL}'

#: How many rows one sheet may carry. Beyond this the export is refused with
#: the number, rather than quietly handing back the newest slice — a
#: truncated ledger that looks complete is worse than no ledger at all.
EXPORT_ROW_LIMIT = 50_000


@router.get('/stock-moves', response_model=KeysetPaginatedResponse[StockMoveRowDTO])
async def list_stock_moves(
    product_template_id: UUID | None = Query(
        None,
        description='Only movements of this product.',
    ),
    location_id: UUID | None = Query(
        None,
        description=(
            'Only movements with either end in this location or anywhere '
            'below it — a location is a tree.'
        ),
    ),
    lot_id: UUID | None = Query(None, description='Only movements of this batch.'),
    reference_type: str | None = Query(
        None,
        max_length=20,
        description="What the movement came from, e.g. 'document'.",
    ),
    reference_id: UUID | None = Query(
        None,
        description='The source itself, e.g. one delivery note.',
    ),
    user_id: UUID | None = Query(
        None, description='Only movements recorded by this person.'
    ),
    direction: str | None = Query(
        None,
        pattern=f'^({_DIRECTIONS})$',
        description=(
            "Read off the pair of locations: 'in' arrived from outside, "
            "'out' left, 'internal' moved between two of your own places."
        ),
    ),
    since: datetime | None = Query(
        None,
        description='Only movements that happened at or after this instant.',
    ),
    until: datetime | None = Query(
        None,
        description='Only movements that happened at or before this instant.',
    ),
    exclude_module_contexts: bool = Query(
        False,
        description=(
            'Leave out the movements of products whose every record belongs to '
            'a vertical module, as the general product list does.'
        ),
    ),
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = Query(
        None,
        description=(
            "The previous page's next_cursor: the page that follows it. The cost "
            'of a page stays its size however deep the ledger goes, and the '
            'count is taken on the first page and carried, so it does not move.'
        ),
    ),
    offset: int = Query(
        0,
        ge=0,
        description=(
            'Deprecated: counts rows from the top on every call, so a deep page '
            'costs every row above it. Page with `cursor`.'
        ),
    ),
    _: object = require_permission(SystemPermission.ITEMS_READ),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """List this organization's stock movements, newest first."""
    org_id = require_org(current_user)
    position = decode_keyset_cursor(cursor) if cursor else None
    served_before = position.offset if position else offset
    # The first page counts only so far (``LIST_COUNT_CAP``): a month of a
    # large warehouse's movements took most of the page to count.
    window = count_window(served_before, limit, LIST_COUNT_CAP)
    # One row more than asked: whether it exists is the whole of "is there a
    # next page", and no count has to be right for that to be so.
    rows, total = await core_api.stock_moves.list_rows_for_org_async(
        db,
        org_id,
        product_template_id=product_template_id,
        location_id=location_id,
        lot_id=lot_id,
        reference_type=reference_type,
        reference_id=reference_id,
        user_id=user_id,
        direction=direction,
        since=since,
        until=until,
        exclude_module_contexts=exclude_module_contexts,
        limit=limit + 1,
        offset=0 if position else offset,
        after=(position.sort_value, position.row_id) if position else None,
        known_total=position.total if position else None,
        count_up_to=window,
    )
    total_capped = position.total_capped if position else total > window
    total = min(total, window)
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = page[-1]
        moved_at = last.completed_at or last.created_at
        if moved_at is None:  # unreachable: created_at is NOT NULL
            raise RuntimeError(f'stock move {last.id} has no date to page by')
        next_cursor = encode_keyset_cursor(
            moved_at,
            last.id,
            total=total,
            offset=served_before + len(page),
            total_capped=total_capped,
        )
    return KeysetPaginatedResponse.from_keyset(
        items=page,
        offset=served_before,
        limit=limit,
        total=total,
        next_cursor=next_cursor,
        total_capped=total_capped,
    )


def _client_timezone(name: str | None) -> ZoneInfo | None:
    """The clock the person who clicked Export is reading, if they said.

    The screens format timestamps in the browser's zone, so a sheet built in
    the organization's zone disagrees with the rows the reader just looked
    at. An unknown or hostile name is not worth an error: the caller falls
    back to the organization's own clock.
    """
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


@router.get('/stock-moves/export/xlsx', response_model=None)
async def export_stock_moves_xlsx(
    product_template_id: UUID | None = Query(None),
    location_id: UUID | None = Query(None),
    lot_id: UUID | None = Query(None),
    reference_type: str | None = Query(None),
    reference_id: UUID | None = Query(None),
    user_id: UUID | None = Query(None),
    direction: str | None = Query(None, pattern=f'^({_DIRECTIONS})$'),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    exclude_module_contexts: bool = Query(False),
    tz: str | None = Query(
        None,
        max_length=64,
        description=(
            "The reader's own IANA time zone, so the sheet agrees with the "
            'screen it was exported from. Falls back to the organization.'
        ),
    ),
    _: object = require_permission(SystemPermission.ITEMS_READ),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """The same question the list answers, as one spreadsheet.

    The person who needs the ledger most — the accountant reconciling a
    quarter, the auditor sampling movements — will not page through a
    screen. Every filter the screen offers is accepted here, and the file
    carries every matching row or none at all.
    """
    org_id = require_org(current_user)
    filters: dict[str, Any] = {
        'product_template_id': product_template_id,
        'location_id': location_id,
        'lot_id': lot_id,
        'reference_type': reference_type,
        'reference_id': reference_id,
        'user_id': user_id,
        'direction': direction,
        'since': since,
        'until': until,
        'exclude_module_contexts': exclude_module_contexts,
    }
    rows, total = await core_api.stock_moves.list_rows_for_org_async(
        db, org_id, limit=EXPORT_ROW_LIMIT, offset=0, **filters
    )
    if total > EXPORT_ROW_LIMIT:
        raise catalogue_refusal(
            'stock_moves_export_too_many', total=total, limit=EXPORT_ROW_LIMIT
        )
    clock = _client_timezone(tz) or await org_timezone_async(db, org_id)
    return to_xlsx_response(
        rows_to_export_frame(rows, clock),
        sheet_name='Movements',
        filename_stem='inventari_stock_moves',
    )
