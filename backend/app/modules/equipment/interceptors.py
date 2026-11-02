from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.context import ModuleContext
from app.core.interceptors import InterceptorError, ItemInterceptor
from app.core.logging import get_logger
from app.core.module_scope import get_context_tags_of
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

logger = get_logger(__name__)


def _incoming_status(changes: dict[str, Any]) -> str | None:
    """The equipment status an update is trying to write, if any."""
    meta_data = changes.get('meta_data') or changes.get('metadata')
    if not isinstance(meta_data, dict):
        return None
    namespace = meta_data.get('equipment')
    if not isinstance(namespace, dict):
        return None
    value = namespace.get('equipment_status')
    return str(value) if value else None


async def _filed_as_equipment(data: dict[str, Any], context: ModuleContext) -> bool:
    """Whether the record is filed under a category the equipment module owns."""
    category_id = data.get('category_id')
    if category_id is None or not context.organization_id:
        return False
    category = await core_api.categories.get_by_id_async(
        context._db, UUID(str(context.organization_id)), UUID(str(category_id))
    )
    return category is not None and category.context_tag in get_context_tags_of(
        'equipment'
    )


class EquipmentItemInterceptor(ItemInterceptor):
    """Block deletion of items that have an active equipment assignment."""

    priority = 50

    async def before_create(
        self, data: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        # Seed a default ``equipment_status`` of AVAILABLE so the
        # dashboard ``by_status`` breakdown does not surface UNKNOWN for
        # freshly-created assets. The value is only written when:
        #   1. The item already carries an ``equipment`` namespace in its
        #      metadata (i.e. it is being created through one of the
        #      equipment-specific paths: bulk-create, import, AddEquipment),
        #      or it is filed under an equipment-tagged category — the
        #      assets list claims such a record whether or not a door that
        #      knows nothing of equipment (a goods receipt) opened it.
        #      Without this guard the interceptor would pollute every
        #      neutral item (food, documents, etc.) with an empty
        #      ``equipment`` namespace and break tests like
        #      ``test_create_item_normalizes_metadata_and_units``.
        #   2. The caller did not already set ``equipment_status``.
        incoming = data.get('meta_data') or data.get('metadata')
        meta_data: dict[str, Any] = incoming if isinstance(incoming, dict) else {}
        equipment_ns = meta_data.get('equipment')
        if not isinstance(equipment_ns, dict):
            if not await _filed_as_equipment(data, context):
                return data
            meta_data = dict(meta_data)
            equipment_ns = {}
        if not equipment_ns.get('equipment_status'):
            equipment_ns['equipment_status'] = 'AVAILABLE'
        meta_data['equipment'] = equipment_ns
        # Normalise both keys so downstream code reading either one sees
        # the same mutated dict (some call sites use ``meta_data``, others
        # ``metadata``).
        data['meta_data'] = meta_data
        if 'metadata' in data:
            data['metadata'] = meta_data
        return data

    async def before_update(
        self, item_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        """Keep the status and the assignment telling the same story.

        Deployment is the shadow of an open assignment: checkout sets the
        status, checkin clears it. Setting it by hand — from the status menu,
        the edit form, or a plain item PATCH — produced a row with an empty
        "checked out to" column and two counters disagreeing about the same
        asset, with nothing in the history to explain it.

        The mirror case is guarded too: an asset cannot be marked available
        while someone still holds it, which would hide an open assignment.

        A row already carrying the status being written is left alone — an
        asset whose status drifted before this guard existed must stay
        editable.
        """
        status = _incoming_status(changes)
        if status not in ('DEPLOYED', 'AVAILABLE'):
            return changes

        db = context._db
        if db is None or not context.organization_id:
            return changes

        from app.core.public_api import core_api
        from app.modules.equipment.models import EquipmentAssignment

        org_id = UUID(str(context.organization_id))
        item = await core_api.items.get_async(db, org_id, item_id)
        current = (
            ((item.meta_data or {}).get('equipment') or {}).get('equipment_status')
            if item is not None
            else None
        )
        if current == status:
            return changes

        active = (
            (
                await db.execute(
                    select(EquipmentAssignment).where(
                        EquipmentAssignment.item_id == item_id,
                        EquipmentAssignment.organization_id == context.organization_id,
                        EquipmentAssignment.checked_in_at.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )
        if status == 'DEPLOYED' and active is None:
            raise InterceptorError(
                get_error_message(
                    'equipment_deploy_requires_checkout', get_current_lang()
                ),
                error_code='EQUIPMENT_NOT_ASSIGNED',
            )
        if status == 'AVAILABLE' and active is not None:
            raise InterceptorError(
                get_error_message('equipment_still_assigned', get_current_lang()),
                error_code='EQUIPMENT_ASSIGNED',
            )
        return changes

    async def before_delete(self, item_id: UUID, context: ModuleContext) -> None:
        from app.modules.equipment.models import EquipmentAssignment

        if not context.organization_id:
            return

        db = context._db
        if db is None:
            return

        result = await db.execute(
            select(EquipmentAssignment).where(
                EquipmentAssignment.item_id == item_id,
                EquipmentAssignment.organization_id == context.organization_id,
                EquipmentAssignment.checked_in_at.is_(None),
            )
        )
        active = result.scalars().first()
        if active:
            # Same wording (and language) as the retire guard in
            # _maintenance_service — one situation, one message.
            raise InterceptorError(
                get_error_message('equipment_still_assigned', get_current_lang()),
                error_code='EQUIPMENT_ASSIGNED',
            )
