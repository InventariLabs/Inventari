from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ServiceRejectionError
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

from ._picking_consume import picking_move_reference
from ._picking_session_helpers import _get_session_or_404
from .models import PickingSession, PickingSessionItem, RecipeIngredient

if TYPE_CHECKING:
    from .schemas import UndoPickResponse

logger = logging.getLogger(__name__)


async def _restore_single_item(
    db: AsyncSession,
    org_id: UUID,
    item_id: UUID,
    consumed: Decimal,
    user_id: UUID | None,
    *,
    consumed_valuation_rate: Decimal | None = None,
    history_changes: dict[str, Any] | None = None,
) -> None:
    """Restore one consumed item: bump quantity + its movement + valuation receipt.

    ``history_changes`` says why the quantity came back. Without it the return
    leg of a pick reads as a bare ``{'old': …, 'new': …}`` — the same shape as
    the take it undoes, and in a household profile there is no other record to
    tell the two apart.
    """
    item = await core_api.items.get_async(db, org_id, item_id)
    if not item:
        return
    new_quantity = (item.quantity or Decimal('0')) + consumed
    actor = user_id if user_id is not None else item.organization_id
    updated = await core_api.items.update_quantity_async(
        db,
        item.organization_id,
        item.id,
        new_quantity,
        user_id=actor,
        history_changes=history_changes,
        sync_valuation=False,
        **picking_move_reference(history_changes),
    )
    if updated is None:
        raise ServiceRejectionError('item_not_found')
    if item.template_id:
        rate = consumed_valuation_rate
        if rate is None:
            rate = await core_api.valuation.get_current_rate_async(
                db, item.organization_id, item.template_id
            )
            if rate is not None and rate > 0:
                logger.warning(
                    'Picking undo for session item %s: consumed_valuation_rate not set, '
                    'falling back to current AVCO rate %s. This may cause cost drift for '
                    'pre-migration rows.',
                    item_id,
                    rate,
                )

        if rate is not None and rate > 0:
            await core_api.valuation.record_receipt_async(
                db,
                item.organization_id,
                item.template_id,
                consumed,
                rate,
            )
        else:
            await core_api.valuation.record_unpriced_receipt_async(
                db,
                item.organization_id,
                item.template_id,
                consumed,
            )


async def _restore_consumption(
    db: AsyncSession,
    org_id: UUID,
    session_item: PickingSessionItem,
    user_id: UUID | None,
    history_changes: dict[str, Any] | None = None,
) -> None:
    """Restore consumed quantity + valuation for a picked session item.

    Supports multi-item partial picks via the ``picked_items`` JSONB
    breakdown.  Falls back to the legacy single-item path (``item_id`` +
    ``quantity_consumed``) when no breakdown is recorded.  Idempotent —
    no-op when nothing was consumed.  Does NOT mutate ``session_item`` or
    commit; the caller owns the transaction and the session-item reset.
    """
    breakdown = session_item.picked_items
    if breakdown:
        for entry in breakdown:
            entry_item_id = entry.get('item_id')
            entry_qty = entry.get('quantity')
            if not entry_item_id or entry_qty is None:
                continue
            await _restore_single_item(
                db,
                org_id,
                UUID(entry_item_id),
                Decimal(str(entry_qty)),
                user_id,
                consumed_valuation_rate=session_item.consumed_valuation_rate,
                history_changes=history_changes,
            )
        return

    if not session_item.item_id or not session_item.quantity_consumed:
        return
    await _restore_single_item(
        db,
        org_id,
        session_item.item_id,
        session_item.quantity_consumed,
        user_id,
        consumed_valuation_rate=session_item.consumed_valuation_rate,
        history_changes=history_changes,
    )


async def undo_pick(
    db: AsyncSession,
    session_id: UUID,
    org_id: UUID,
    ingredient_id: UUID,
) -> UndoPickResponse:
    from .schemas import UndoPickResponse as _UndoPickResponse

    lang = get_current_lang()
    await _get_session_or_404(db, session_id, org_id)
    session_res = await db.execute(
        select(PickingSession).where(PickingSession.id == session_id).with_for_update()
    )
    picking_session = session_res.scalars().first()

    result = await db.execute(
        select(PickingSessionItem)
        .where(
            PickingSessionItem.session_id == session_id,
            PickingSessionItem.ingredient_id == ingredient_id,
            PickingSessionItem.status == 'picked',
        )
        .with_for_update()
    )
    session_item = result.scalars().first()
    if not session_item:
        raise AppException(
            status_code=404,
            code='INGREDIENT_NOT_FOUND_OR_NOT_PICKED',
            message=get_error_message('ingredient_not_found_or_not_picked', lang),
        )

    if session_item.item_id and session_item.quantity_consumed:
        await _restore_consumption(
            db,
            org_id,
            session_item,
            picking_session.user_id if picking_session else None,
            history_changes={
                'reason': 'recipe_picking_undo',
                'picking_session_id': str(session_id),
                'ingredient_name': session_item.ingredient_name,
            },
        )

    restored = session_item.quantity_consumed or Decimal('0')
    session_item.status = 'pending'
    session_item.item_id = None
    session_item.quantity_consumed = None
    session_item.picked_items = None
    await db.flush()

    final_ing_result = await db.execute(
        select(RecipeIngredient).where(RecipeIngredient.id == ingredient_id)
    )
    ingredient = final_ing_result.scalars().first()
    uom_symbol = ingredient.uom.symbol if ingredient and ingredient.uom else None

    return _UndoPickResponse(
        ingredient_id=ingredient_id,
        ingredient_name=ingredient.name if ingredient else '',
        restored_quantity=restored,
        uom_symbol=uom_symbol,
    )
