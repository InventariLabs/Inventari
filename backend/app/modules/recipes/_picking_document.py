"""Optional RW document registration for completed picking sessions.

Cross-module integration (documents) with graceful degradation:
- toggle ``register_production_as_document`` (per-org module setting,
  default off) enables the audit-trail document
- when the warehouse module is disabled, this is a silent no-op

The document is created as DRAFT: the stock was already consumed by the
picking flow (``core_api.items.update_quantity_async``), so confirming or
completing it would double-apply the stock delta. The draft keeps the
movement in the document register for audit/accounting exports.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.core.public_api import core_api

from .models import PickingSession, PickingSessionItem, RecipeIngredient

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


def _ingredient_uom(
    info: dict[UUID, tuple[UUID | None, str]], item: PickingSessionItem
) -> UUID | None:
    if item.ingredient_id and item.ingredient_id in info:
        return info[item.ingredient_id][0]
    return None


def _ingredient_label(
    info: dict[UUID, tuple[UUID | None, str]], item: PickingSessionItem
) -> str:
    """Name the line — falling back to the snapshot when the ingredient is gone."""
    if item.ingredient_id and item.ingredient_id in info:
        return info[item.ingredient_id][1]
    return item.ingredient_name or ''


_SETTING_KEY = 'register_production_as_document'

# Document notes per request language (fallback: English). Server-generated
# content must not be hardcoded English — see protocol_service pattern.
_NOTES_LABELS: dict[str, str] = {
    'en': (
        'Recipe production: {recipe} — stock already consumed '
        'via picking session {session}'
    ),
    'pl': (
        'Produkcja z receptury: {recipe} — stan został już pobrany '
        'w sesji kompletacji {session}'
    ),
    'de': (
        'Rezeptproduktion: {recipe} — Bestand bereits über '
        'Kommissioniersitzung {session} entnommen'
    ),
    'fr': (
        'Production de recette : {recipe} — stock déjà consommé '
        'via la session de prélèvement {session}'
    ),
    'es': (
        'Producción de receta: {recipe} — existencias ya consumidas '
        'en la sesión de picking {session}'
    ),
}


async def register_picking_as_document_async(
    db: AsyncSession,
    session: PickingSession,
    org_id: UUID,
    user_id: UUID,
    lang: str = 'en',
) -> str | None:
    """Create an RW audit document for a completed picking session.

    Returns the document id, or ``None`` when the feature is off, the
    warehouse module is disabled, or there is nothing to record.
    """
    enabled = await core_api.settings.get_async(
        db, org_id, 'recipes', _SETTING_KEY, default=False
    )
    if not enabled:
        return None

    docs_enabled = await core_api.organizations.is_module_enabled_async(
        db, org_id, 'warehouse'
    )
    if not docs_enabled:
        return None

    picked = [i for i in session.items if i.status == 'picked' and i.item_id]
    if not picked:
        return None

    try:
        from app.modules.warehouse.schemas import DocumentCreate, DocumentLineCreate
        from app.modules.warehouse.warehouse_api import warehouse_api

        first_item_id = picked[0].item_id
        if first_item_id is None:
            return None
        first_item = await core_api.items.get_async(db, org_id, first_item_id)
        source_location_id = first_item.location_id if first_item else None
        if source_location_id is None:
            log.warning(
                'register_picking_as_document: picked item %s has no storage '
                'location — skipping RW document for session %s',
                picked[0].item_id,
                session.id,
            )
            return None

        # UOM + name per ingredient (loaded explicitly — the session loader
        # does not selectinload PickingSessionItem.ingredient).
        ingredient_info: dict[UUID, tuple[UUID | None, str]] = {}
        ingredient_ids = [i.ingredient_id for i in picked if i.ingredient_id]
        result = await db.execute(
            select(
                RecipeIngredient.id, RecipeIngredient.uom_id, RecipeIngredient.name
            ).where(RecipeIngredient.id.in_(ingredient_ids))
        )
        for ing_id, uom_id, name in result.all():
            ingredient_info[ing_id] = (uom_id, name)

        lines = [
            DocumentLineCreate(
                item_id=item.item_id,
                expected_quantity=item.quantity_consumed or Decimal('0'),
                uom_id=_ingredient_uom(ingredient_info, item),
                # Valuation snapshot taken at consume time — same layer the
                # picking flow used, never recomputed
                unit_price=item.consumed_valuation_rate,
                notes=_ingredient_label(ingredient_info, item),
            )
            for item in picked
        ]

        # Recipe identity in the notes (session.recipe is selectin-loaded;
        # fall back to the id if the relation was never populated).
        recipe_name = session.recipe.name if session.recipe else str(session.recipe_id)

        doc = await warehouse_api.create_document_draft_async(
            db,
            org_id,
            DocumentCreate(
                type='INTERNAL_OUT',
                source_location_id=source_location_id,
                lines=lines,
                notes=_NOTES_LABELS.get(lang, _NOTES_LABELS['en']).format(
                    recipe=recipe_name,
                    session=session.id,
                ),
                external_reference=f'picking:{session.id}',
            ),
            user_id,
        )

        # Link session → document (parsed by the cooking history UI)
        existing = (session.notes or '').strip()
        session.notes = (
            f'{existing}\ndocument: {doc.id}'.strip()
            if existing
            else f'document: {doc.id}'
        )
        await db.flush()
        log.info(
            'Registered RW document %s for picking session %s (%d lines)',
            doc.id,
            session.id,
            len(lines),
        )
        return str(doc.id)
    except Exception:  # audit trail must never break completion
        log.exception(
            'register_picking_as_document: failed for session %s — '
            'completion continues without document',
            session.id,
        )
        return None
