"""GET /api/v1/audit-log — list audit entries for the current org.

Filters exposed: target_type, target_id,
user_id, actor (a key's work or a person's), since/until (ISO datetime),
limit (max 500, default 100).

Authentication: admin only — the log contains activity
metadata of all org members. The endpoint is org-scoped via
``require_org`` so other organisations' entries can never leak. Writes
happen via dedicated ``audit_service.log_action_async`` callers
(CREATE / UPDATE / SOFT_DELETE instrumentation) and a separate
``log_purge_async`` path — this endpoint is read-only by design.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_current_admin_user
from app.core.contracts import AuditLogDTO, UserContextDTO
from app.core.cursor import decode_keyset_cursor, encode_keyset_cursor
from app.core.db_utils import LIST_COUNT_CAP, count_window
from app.core.deps import get_async_db, require_org
from app.core.public_api import core_api
from app.schemas.pagination import KeysetPaginatedResponse

router = APIRouter()

#: What `actor` accepts: a key's entries, or everything else — including the
#: rows written before a key was ever named, which is why the other value is
#: "human" and not "the actor is a person".
AuditActorFilter = Literal['human', 'api_key']


@router.get('/audit-log', response_model=KeysetPaginatedResponse[AuditLogDTO])
async def list_audit_log(
    target_type: str | None = Query(None, max_length=50),
    target_id: UUID | None = Query(None),
    user_id: UUID | None = Query(None),
    actor: AuditActorFilter | None = Query(
        None, description="'api_key' for entries an API key wrote, 'human' for the rest"
    ),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = Query(
        None,
        description=(
            "The previous page's next_cursor: the page that follows it. The cost "
            'of a page stays its size however long the journal is, and the count '
            'is taken on the first page and carried, so it does not move.'
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
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    org_id = require_org(current_user)
    position = decode_keyset_cursor(cursor) if cursor else None
    served_before = position.offset if position else offset
    # The first page counts only so far (``LIST_COUNT_CAP``), as the movement
    # journal does: every action writes an entry, so the count grew with the
    # organization's whole history.
    window = count_window(served_before, limit, LIST_COUNT_CAP)
    # One entry more than asked: whether it exists is the whole of "is there a
    # next page", and no count has to be right for that to be so.
    rows, total = await core_api.audit_log.list_for_org_async(
        db,
        org_id,
        target_type=target_type,
        target_id=target_id,
        user_id=user_id,
        actor=actor,
        since=since,
        until=until,
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
        next_cursor = encode_keyset_cursor(
            last.created_at,
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


@router.get(
    '/audit-log/target-types',
    # list-envelope-exception: a vocabulary, one entry per kind of record logged
    response_model=list[str],
)
async def list_audit_target_types(
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
) -> list[str]:
    """The kinds of thing this organization's log actually records.

    The screen's filter listed three values typed by hand, two of them from
    modules the profile does not install; the things that really changed had
    no entry on it. Reading the log is the only way the filter cannot offer a
    choice that matches nothing.
    """
    org_id = require_org(current_user)
    return await core_api.audit_log.list_target_types_async(db, org_id)
