from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import paginate_async

from ._holder import holder_of_assignment
from ._serial import serial_of
from .models import EquipmentAssignment
from .status_machine import resolve_previous_status


async def get_my_active_assets(
    db: AsyncSession, org_id: UUID, user_email: str
) -> list[dict[str, Any]]:
    from app.core.public_api import core_api

    partners = await core_api.partners.list_by_email_async(db, org_id, user_email)
    partner_ids = [p.id for p in partners] if partners else []

    # legacy rows may carry mixed-case emails — compare lowercase.
    email_lc = user_email.lower()
    query = (
        select(EquipmentAssignment)
        .where(
            EquipmentAssignment.organization_id == org_id,
            EquipmentAssignment.checked_in_at.is_(None),
        )
        .order_by(EquipmentAssignment.checked_out_at.desc())
    )
    if partner_ids:
        query = query.where(
            or_(
                EquipmentAssignment.assignee_partner_id.in_(partner_ids),
                func.lower(EquipmentAssignment.assigned_to_email) == email_lc,
            )
        )
    else:
        query = query.where(
            func.lower(EquipmentAssignment.assigned_to_email) == email_lc
        )

    result_rows = await db.execute(query)
    assignments = result_rows.scalars().all()

    result = []
    # A unit created from a model has no picture of its own — a batch is
    # created in one call with nowhere to upload one photo per unit — so it
    # borrows the model's. Cached per call: a fleet is usually a few models.
    model_images: dict[str, str | None] = {}

    async def _model_image(model_id: str | None) -> str | None:
        if not model_id:
            return None
        if model_id not in model_images:
            try:
                model = await core_api.product_templates.get_async(
                    db, org_id, UUID(model_id)
                )
            except ValueError:
                model = None
            model_images[model_id] = getattr(model, 'image_url', None)
        return model_images[model_id]

    for a in assignments:
        item = await core_api.items.get_async(db, org_id, a.item_id)
        if not item:
            continue
        eq_meta = (item.meta_data or {}).get('equipment', {})
        holder = holder_of_assignment(a)
        result.append(
            {
                'assignment_id': a.id,
                'item_id': a.item_id,
                'item_name': item.name if item else '',
                'item_barcode': item.barcode if item else None,
                'category_name': item.category.name if item.category else None,
                'category_code': item.category.code if item.category else None,
                'checked_out_at': a.checked_out_at,
                'expected_return_at': a.expected_return_at,
                'checkout_notes': a.checkout_notes,
                'equipment_status': resolve_previous_status(
                    eq_meta.get('equipment_status')
                ),
                'warranty_until': eq_meta.get('warranty_until'),
                'serial_number': serial_of(item),
                'image_url': getattr(item, 'image_url', None),
                'model_image_url': await _model_image(eq_meta.get('model_id')),
                'holder_name': holder.name if holder is not None else None,
                'holder_kind': holder.kind if holder is not None else None,
            }
        )
    return result


async def get_my_assignment_history(
    db: AsyncSession, org_id: UUID, user_email: str, limit: int = 50, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    from app.core.public_api import core_api

    partners = await core_api.partners.list_by_email_async(db, org_id, user_email)
    partner_ids = [p.id for p in partners] if partners else []

    # legacy rows may carry mixed-case emails — compare lowercase.
    email_lc = user_email.lower()
    query = (
        select(EquipmentAssignment)
        .where(
            EquipmentAssignment.organization_id == org_id,
            EquipmentAssignment.checked_in_at.isnot(None),
        )
        .order_by(
            EquipmentAssignment.checked_in_at.desc(), EquipmentAssignment.id.desc()
        )
    )
    if partner_ids:
        query = query.where(
            or_(
                EquipmentAssignment.assignee_partner_id.in_(partner_ids),
                func.lower(EquipmentAssignment.assigned_to_email) == email_lc,
            )
        )
    else:
        query = query.where(
            func.lower(EquipmentAssignment.assigned_to_email) == email_lc
        )

    assignments, total = await paginate_async(db, query, limit=limit, offset=offset)

    result = []
    for a in assignments:
        # The history is exactly the record of what was: an asset archived
        # after its return still answers the row it left behind. The
        # live-only read emptied the name and dead-ended the link into a
        # card the reader could not open.
        item = await core_api.items.get_any_async(db, org_id, a.item_id)
        item_name = item.name if item else ''
        result.append(
            {
                'assignment_id': a.id,
                'item_id': a.item_id,
                'item_name': item_name,
                'checked_out_at': a.checked_out_at,
                'checked_in_at': a.checked_in_at,
                'checkin_condition': a.checkin_condition,
            }
        )
    return result, total
