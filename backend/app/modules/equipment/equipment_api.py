"""The equipment module's public API for other modules.

This is the one door another module may use to read the asset register and
to hand an asset out or take it back. The rentals module is the first
consumer: a booking's pickup and return travel through these methods, so the
status machine, the item history, the organization journal, the approval
gate and the hand-over events stay in one place (backend/AGENTS.md,
cross-module API contracts).

Every method answers a sensible empty value while this module is switched
off, so a consumer that is enabled on its own does not crash on import or on
the first call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from ._assets_service import list_equipment_assets_async
from ._schemas_assignment import AssignmentCheckin, AssignmentCreate
from .models import EquipmentAssignment


class EquipmentAssetDTO(BaseModel):
    """An asset as another module sees it: which unit, which model, whose hands."""

    id: UUID
    name: str
    model: str | None = None
    category_id: UUID | None = None
    category_name: str | None = None
    status: str = 'AVAILABLE'
    serial_number: str | None = None
    asset_tag: str | None = None
    barcode: str | None = None
    #: The open assignment, when somebody holds the asset right now.
    assignment_id: UUID | None = None
    holder_name: str | None = None
    assignment_started_at: datetime | None = None
    assignment_expected_return_at: datetime | None = None


class EquipmentAssignmentRefDTO(BaseModel):
    """What a hand-out leaves behind, and what a return needs to close it."""

    assignment_id: UUID
    item_id: UUID
    checked_out_at: datetime
    expected_return_at: datetime | None = None
    checked_in_at: datetime | None = None


def _model_of(item: Any) -> str | None:
    """Which model a unit is: its catalogue row, else the free-text field.

    An asset created through the register names a product template, and that
    row is the model — the free-text ``model`` in the equipment namespace is
    a specification scribble, not the grouping identity. The fallback keeps
    assets that predate the template (and a hand-made one without it)
    groupable.
    """
    template = getattr(item, 'template', None)
    if template is not None and getattr(template, 'name', None):
        return str(template.name)
    meta = item.meta_data or {}
    model = str((meta.get('equipment') or {}).get('model') or '').strip()
    return model or None


def _asset_dto(item: Any, assignment: EquipmentAssignment | None) -> EquipmentAssetDTO:
    meta = item.meta_data or {}
    equipment_ns = meta.get('equipment') or {}
    serial = item.serial_number or equipment_ns.get('serial_number')
    holder = None
    if assignment is not None:
        from ._holder import holder_of_assignment

        resolved = holder_of_assignment(assignment)
        holder = resolved.name if resolved is not None else None
    return EquipmentAssetDTO(
        id=item.id,
        name=item.name,
        model=_model_of(item),
        category_id=item.category_id,
        category_name=item.category.name if item.category is not None else None,
        status=str(equipment_ns.get('equipment_status') or 'AVAILABLE'),
        serial_number=str(serial) if serial else None,
        asset_tag=(
            str(equipment_ns.get('asset_tag'))
            if equipment_ns.get('asset_tag')
            else None
        ),
        barcode=item.barcode,
        assignment_id=assignment.id if assignment is not None else None,
        holder_name=holder,
        assignment_started_at=(
            assignment.checked_out_at if assignment is not None else None
        ),
        assignment_expected_return_at=(
            assignment.expected_return_at if assignment is not None else None
        ),
    )


class EquipmentAPI:
    """The equipment module's contract for its neighbours."""

    @staticmethod
    async def is_enabled_async(db: AsyncSession, org_id: UUID) -> bool:
        return await core_api.organizations.is_module_enabled_async(
            db, org_id, 'equipment'
        )

    @staticmethod
    async def list_bookable_assets_async(
        db: AsyncSession,
        org_id: UUID,
        *,
        search: str | None = None,
        category_id: UUID | None = None,
        include_retired: bool = False,
    ) -> list[EquipmentAssetDTO]:
        """Every asset a booking may name, with the open hand-out attached.

        Retired assets are left out: a booking of a retired unit is a booking
        of something nobody will hand out.
        """
        if not await EquipmentAPI.is_enabled_async(db, org_id):
            return []
        items, _total, _holders = await list_equipment_assets_async(
            db,
            org_id,
            search=search,
            category_id=category_id,
            hide_retired=not include_retired,
            limit=1000,
            offset=0,
        )
        ids = [item.id for item in items]
        open_assignments: dict[UUID, EquipmentAssignment] = {}
        if ids:
            rows = (
                (
                    await db.execute(
                        select(EquipmentAssignment).where(
                            EquipmentAssignment.organization_id == org_id,
                            EquipmentAssignment.item_id.in_(ids),
                            EquipmentAssignment.checked_in_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            open_assignments = {row.item_id: row for row in rows}
        return [_asset_dto(item, open_assignments.get(item.id)) for item in items]

    @staticmethod
    @staticmethod
    async def checkout_async(
        db: AsyncSession,
        org_id: UUID,
        *,
        item_id: UUID,
        assigned_to_name: str,
        user_id: UUID,
        assigned_to_email: str | None = None,
        assignee_partner_id: UUID | None = None,
        expected_return_at: datetime | None = None,
        notes: str | None = None,
    ) -> EquipmentAssignmentRefDTO | None:
        """Hand an asset out. The caller owns the transaction.

        The expected return is used as given: a booking knows its window to
        the minute, unlike the register's own form, whose return is a day.
        """
        if not await EquipmentAPI.is_enabled_async(db, org_id):
            return None
        # Imported here, not at module scope: the assignment service reaches
        # back into ``services`` for its shared readers, and the public API is
        # imported by a consumer before either of them has finished loading.
        from ._assignment_service import checkout

        assignment = await checkout(
            db,
            org_id,
            AssignmentCreate(
                item_id=item_id,
                assigned_to_name=assigned_to_name,
                assigned_to_email=assigned_to_email,
                assignee_partner_id=assignee_partner_id,
                expected_return_at=expected_return_at,
                checkout_notes=notes,
            ),
            user_id,
            pin_expected_return=False,
        )
        return EquipmentAssignmentRefDTO(
            assignment_id=assignment.id,
            item_id=assignment.item_id,
            checked_out_at=assignment.checked_out_at,
            expected_return_at=assignment.expected_return_at,
            checked_in_at=assignment.checked_in_at,
        )

    @staticmethod
    async def checkin_async(
        db: AsyncSession,
        org_id: UUID,
        *,
        assignment_id: UUID,
        user_id: UUID,
        condition: str | None = None,
        notes: str | None = None,
    ) -> EquipmentAssignmentRefDTO | None:
        """Take an asset back, recording its condition. The caller commits."""
        if not await EquipmentAPI.is_enabled_async(db, org_id):
            return None
        from ._assignment_service import checkin

        assignment = await checkin(
            db,
            org_id,
            assignment_id,
            AssignmentCheckin(checkin_notes=notes, checkin_condition=condition),
            user_id,
        )
        return _assignment_ref_from_schema(assignment)

    @staticmethod
    async def set_expected_return_async(
        db: AsyncSession,
        org_id: UUID,
        *,
        assignment_id: UUID,
        expected_return_at: datetime,
        user_id: UUID,
    ) -> bool:
        """Move the return a hand-out expects, keeping the journal honest."""
        from datetime import UTC

        from app.core.contracts import AuditAction, AuditTargetType

        from ._unit_identity import audit_identity

        row = (
            (
                await db.execute(
                    select(EquipmentAssignment).where(
                        EquipmentAssignment.id == assignment_id,
                        EquipmentAssignment.organization_id == org_id,
                        EquipmentAssignment.checked_in_at.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            return False
        before = row.expected_return_at
        row.expected_return_at = expected_return_at
        await db.flush()
        item = await core_api.items.get_async(db, org_id, row.item_id)
        await core_api.audit_log.log_action_async(
            db,
            organization_id=org_id,
            user_id=user_id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.EQUIPMENT_ASSIGNMENT,
            target_id=row.id,
            snapshot={
                **(audit_identity(item) if item is not None else {}),
                'before': {
                    'expected_return_at': (
                        before.isoformat() if before is not None else None
                    )
                },
                'after': {
                    'expected_return_at': expected_return_at.isoformat(),
                    'moved_at': datetime.now(UTC).isoformat(),
                },
            },
        )
        return True


def _assignment_ref(row: EquipmentAssignment) -> EquipmentAssignmentRefDTO:
    return EquipmentAssignmentRefDTO(
        assignment_id=row.id,
        item_id=row.item_id,
        checked_out_at=row.checked_out_at,
        expected_return_at=row.expected_return_at,
        checked_in_at=row.checked_in_at,
    )


def _assignment_ref_from_schema(schema: Any) -> EquipmentAssignmentRefDTO:
    return EquipmentAssignmentRefDTO(
        assignment_id=schema.id,
        item_id=schema.item_id,
        checked_out_at=schema.checked_out_at,
        expected_return_at=schema.expected_return_at,
        checked_in_at=schema.checked_in_at,
    )


equipment_api = EquipmentAPI()
