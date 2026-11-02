from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.events import RecipePickingCompletedPayload
from app.core.exceptions import NotFoundException
from app.core.public_api import core_api

from ._picking_fefo import (
    FEFO_URGENCY_THRESHOLD_DAYS,
    _fefo_sort_key,
    _resolve_user_id,
    _should_auto_skip,
    needs_disambiguation,
    select_best_item,
)
from ._picking_helpers import check_opened_suggestion, is_opened
from ._picking_lifecycle import terminate_session
from ._picking_refresh import read_picking_session
from ._picking_scan import scan_item_in_picking
from ._picking_session import record_cooking_session, start_picking_session
from ._picking_session_helpers import (
    _build_disambiguation,
    _get_session_or_404,
    _ingredient_to_checklist_item,
    _match_ingredient,
)
from ._picking_undo import undo_pick
from .events import RecipeEvent
from .models import PickingSession, PickingSessionItem

__all__ = [
    'FEFO_URGENCY_THRESHOLD_DAYS',
    '_UNSET',
    '_Unset',
    '_build_disambiguation',
    '_fefo_sort_key',
    '_get_session_or_404',
    '_ingredient_to_checklist_item',
    '_match_ingredient',
    '_resolve_user_id',
    '_should_auto_skip',
    'cancel_picking_session',
    'check_opened_suggestion',
    'complete_picking_session',
    'is_opened',
    'needs_disambiguation',
    'read_picking_session',
    'record_cooking_session',
    'scan_item_in_picking',
    'select_best_item',
    'start_picking_session',
    'undo_pick',
    'update_cooking_history_session',
]


class _Unset:
    """Sentinel for 'value not provided' in partial updates."""


_UNSET = _Unset()


async def complete_picking_session(
    db: AsyncSession, session_id: UUID, org_id: UUID, lang: str = 'en'
) -> dict[str, str]:
    # The last pick closes the session itself, so this endpoint has to answer
    # the same thing twice rather than 404 on a session it just finished.
    session = await _get_session_or_404(
        db, session_id, org_id, for_update=True, include_terminal=True
    )
    if session.status == 'completed':
        return {'status': 'completed', 'session_id': str(session_id)}
    if session.status != 'active':
        raise NotFoundException('picking_session')
    session.status = 'completed'
    session.completed_at = datetime.now(UTC)

    consumed_items = (
        await db.scalars(
            select(PickingSessionItem)
            .where(
                PickingSessionItem.session_id == session_id,
                PickingSessionItem.status == 'picked',
            )
            .with_for_update()
        )
    ).all()
    await core_api.events.emit_transactional_async(
        db,
        RecipeEvent.PICKING_COMPLETED,
        RecipePickingCompletedPayload(
            organization_id=str(org_id),
            session_id=str(session_id),
            recipe_id=str(session.recipe_id),
            servings=session.servings,
            items_consumed=[
                {
                    'item_id': str(item.item_id) if item.item_id else None,
                    'ingredient_id': str(item.ingredient_id)
                    if item.ingredient_id
                    else None,
                    'quantity_consumed': float(item.quantity_consumed)
                    if item.quantity_consumed is not None
                    else None,
                }
                for item in consumed_items
            ],
        ),
    )
    await db.flush()
    # Optional audit-trail RW document (no-op unless configured)
    from ._picking_document import register_picking_as_document_async

    await register_picking_as_document_async(
        db, session, org_id, session.user_id, lang=lang
    )
    return {'status': 'completed', 'session_id': str(session_id)}


async def update_cooking_history_session(
    db: AsyncSession,
    session_id: UUID,
    recipe_id: UUID,
    org_id: UUID,
    notes: str | None | _Unset = _UNSET,
    rating: int | None | _Unset = _UNSET,
) -> PickingSession | None:
    result = await db.execute(
        select(PickingSession).where(
            PickingSession.id == session_id,
            PickingSession.recipe_id == recipe_id,
            PickingSession.organization_id == org_id,
            PickingSession.status == 'completed',
        )
    )
    session = result.scalars().first()
    if not session:
        return None
    if not isinstance(notes, _Unset):
        session.notes = notes
    if not isinstance(rating, _Unset):
        session.rating = rating
    await db.flush()
    await db.refresh(session)
    return session


async def cancel_picking_session(
    db: AsyncSession, session_id: UUID, org_id: UUID
) -> None:
    # Include terminal sessions for idempotent cancel
    session = await _get_session_or_404(db, session_id, org_id, include_terminal=True)
    if session.status == 'cancelled':
        # Already cancelled — idempotent no-op
        return
    await terminate_session(db, session, reason='cancel')
    await db.flush()
