"""Picking session lifecycle: terminate sessions with stock restoration.

Extracts the shared terminate logic used by:
- Cancel (cancel_picking_session)
- Recipe delete (delete_recipe)
- Recipe edit guard (update_recipe)

Starting a session is not on this list any more: an unfinished session is
handed back to be finished, because throwing it away puts the ingredients of
a meal that was already cooked back on the shelf.
"""

from __future__ import annotations

import logging
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError

from ._picking_undo import _restore_consumption
from .models import PickingSession, PickingSessionItem

logger = logging.getLogger(__name__)

_TERMINAL_REASONS = {'cancel', 'recipe_delete', 'recipe_edit'}


async def terminate_session(
    db: AsyncSession,
    session: PickingSession,
    reason: Literal['cancel', 'recipe_delete', 'recipe_edit'],
) -> None:
    """Terminate a picking session and restore all consumed stock.

    Loads every ``PickingSessionItem`` with ``status='picked'`` for the
    session, calls ``_restore_consumption`` on each, resets the item state,
    and marks the session as terminal.  The caller owns the commit.

    Parameters
    ----------
    db:
        Async database session.
    session:
        The ``PickingSession`` to terminate.  Must be attached to *db*.
    reason:
        Why the session is being terminated.  Logged per item in its history
        and into the application log — never into the user's note.
    """
    if reason not in _TERMINAL_REASONS:
        raise ServiceRejectionError('picking_terminate_reason_invalid', reason=reason)

    picked_result = await db.execute(
        select(PickingSessionItem).where(
            PickingSessionItem.session_id == session.id,
            PickingSessionItem.status == 'picked',
        )
    )
    picked_items = list(picked_result.scalars().all())

    for item in picked_items:
        await _restore_consumption(
            db,
            session.organization_id,
            item,
            session.user_id,
            history_changes={
                'reason': 'recipe_picking_cancelled',
                'picking_session_id': str(session.id),
                'ingredient_name': item.ingredient_name,
                'terminated': reason,
            },
        )
        item.status = 'pending'
        item.item_id = None
        item.quantity_consumed = None
        item.picked_items = None

    # The reason travels in the item history (``terminated`` above) and in
    # the log line below — the cook's own note field is the user's, and
    # ``terminated: cancel`` glued to "came out thin, less milk next time"
    # read as part of what they wrote.
    session.status = 'cancelled'

    logger.info(
        'Terminated picking session %s (reason=%s, restored %d picked items)',
        session.id,
        reason,
        len(picked_items),
    )
