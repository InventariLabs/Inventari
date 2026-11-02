"""
Equipment module business logic.

Handles check-out/check-in, maintenance logs, and bulk item creation.
Services only — no HTTP concerns here.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import get_org_owned_or_404_async
from app.core.logging import get_logger
from app.i18n.service import get_current_lang

from ._holder import holder_of_parts
from ._unit_identity import unit_identifiers
from .models import EquipmentAssignment, EquipmentMaintenanceLog
from .schemas import AssignmentSchema, MaintenanceLogSchema

logger = get_logger(__name__)


async def _get_assignment_or_404(
    db: AsyncSession, assignment_id: UUID, org_id: UUID
) -> EquipmentAssignment:
    return await get_org_owned_or_404_async(
        db, EquipmentAssignment, assignment_id, org_id, resource='assignment'
    )


async def _get_log_or_404(
    db: AsyncSession, log_id: UUID, org_id: UUID
) -> EquipmentMaintenanceLog:
    return await get_org_owned_or_404_async(
        db, EquipmentMaintenanceLog, log_id, org_id, resource='maintenance_log'
    )


def _to_assignment_schema(
    assignment: EquipmentAssignment,
    operator_names: dict[UUID, str] | None = None,
) -> AssignmentSchema:
    item_name = assignment.item.name if assignment.item else ''
    partner_name = (
        assignment.assignee_partner.name
        if assignment.assignee_partner is not None
        else None
    )
    checkout_location_name = (
        assignment.checkout_location.name
        if assignment.checkout_location is not None
        else None
    )
    serial, asset_tag = unit_identifiers(assignment.item)
    names = operator_names or {}
    holder = holder_of_parts(
        partner_name=partner_name,
        assigned_to_name=assignment.assigned_to_name,
        checkout_location_name=checkout_location_name,
    )
    return AssignmentSchema(
        id=assignment.id,
        item_id=assignment.item_id,
        item_name=item_name,
        item_serial=serial,
        item_asset_tag=asset_tag,
        assignee_partner_id=assignment.assignee_partner_id,
        partner_name=partner_name,
        checkout_location_id=assignment.checkout_location_id,
        checkout_location_name=checkout_location_name,
        assigned_to_name=assignment.assigned_to_name,
        assigned_to_email=assignment.assigned_to_email,
        holder_name=holder.name if holder is not None else None,
        holder_kind=holder.kind if holder is not None else None,
        checked_out_at=assignment.checked_out_at,
        expected_return_at=assignment.expected_return_at,
        checked_in_at=assignment.checked_in_at,
        checked_out_by=assignment.checked_out_by,
        checked_in_by=assignment.checked_in_by,
        checked_out_by_name=names.get(assignment.checked_out_by),
        checked_in_by_name=(
            names.get(assignment.checked_in_by) if assignment.checked_in_by else None
        ),
        checkout_notes=assignment.checkout_notes,
        checkin_notes=assignment.checkin_notes,
        checkin_condition=assignment.checkin_condition,
        created_at=assignment.created_at,
    )


def _to_maintenance_schema(log: EquipmentMaintenanceLog) -> MaintenanceLogSchema:
    item_name = log.item.name if log.item else ''
    return MaintenanceLogSchema(
        id=log.id,
        item_id=log.item_id,
        item_name=item_name,
        maintenance_type=log.maintenance_type,
        title=log.title,
        description=log.description,
        cost=log.cost,
        currency=log.currency,
        performed_at=log.performed_at,
        performed_by=log.performed_by,
        service_partner_id=log.service_partner_id,
        next_maintenance_at=log.next_maintenance_at,
        created_by=log.created_by,
        created_at=log.created_at,
    )


async def _log_item_history(
    db: AsyncSession,
    item_id: UUID,
    org_id: UUID,
    user_id: UUID,
    action: str,
    changes: dict[str, Any],
) -> None:
    from app.core.public_api import core_api

    await core_api.item_history.log_async(
        db,
        item_id=item_id,
        organization_id=org_id,
        user_id=user_id,
        action=action,
        changes=changes,
    )


async def _update_equipment_status(
    db: AsyncSession, item_id: UUID, org_id: UUID, status_value: str
) -> None:
    # Enforce the status state machine on every write path
    # (checkout/checkin/maintenance). Previously each caller wrote the new
    # status directly into meta_data, bypassing ``validate_transition``;
    # that allowed illegal transitions (e.g. RETIRED → DEPLOYED via a
    # stale code path). The caller is expected to catch ``ValueError`` and
    # translate it into an HTTP 400.
    from app.core.public_api import core_api

    from .status_machine import validate_transition

    lang = get_current_lang()
    item = await core_api.items.get_async(db, org_id, item_id)
    if not item:
        return

    equipment_ns = (item.meta_data or {}).get('equipment', {})
    old_status = equipment_ns.get('equipment_status', 'UNKNOWN')

    validate_transition(old_status, status_value, lang)

    await core_api.items.update_meta_data_async(
        db,
        organization_id=org_id,
        item_id=item_id,
        namespace='equipment',
        data={'equipment_status': status_value},
    )


from ._assignment_service import (  # noqa: E402
    bulk_checkin_items,
    checkin,
    checkout,
    count_item_assignment_history,
    get_item_assignment_history,
    list_active_assignments,
)
from ._bulk_service import bulk_create_items  # noqa: E402
from ._maintenance_service import (  # noqa: E402
    archive_item,
    count_item_logs,
    create_log,
    delete_log,
    get_item_logs,
    retire_item,
    update_log,
)
from ._overdue_service import list_overdue_assignments  # noqa: E402,F401
from .bulk_service import bulk_edit_items  # noqa: E402

__all__ = [
    'archive_item',
    'bulk_checkin_items',
    'bulk_create_items',
    'bulk_edit_items',
    'checkout',
    'checkin',
    'count_item_assignment_history',
    'count_item_logs',
    'create_log',
    'delete_log',
    'get_item_assignment_history',
    'get_item_logs',
    'list_active_assignments',
    'list_overdue_assignments',
    'retire_item',
    'update_log',
]
