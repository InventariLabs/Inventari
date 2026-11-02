"""List overdue equipment assignments.

``OverdueAssignmentItem`` and ``OverdueAssignmentListResponse`` were
declared but no service / router wired them. Without this endpoint,
the dashboard cannot surface "this laptop was supposed to come back
last week" and the chrome for the overdue list was dead code.

Contract:
- Returns assignments whose ``expected_return_at`` is in the past.
- Includes ``days_overdue`` so the FE can colour-code without having to
  re-derive it client-side.
- Excludes already-checked-in rows (``checked_in_at IS NULL``).
- Pagination via ``limit`` / ``offset`` matching the existing
  ``AssignmentListResponse`` shape so the FE can reuse one fetcher.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db_utils import paginate_async

from ._holder import holder_of_assignment
from ._unit_identity import unit_identifiers
from .models import EquipmentAssignment
from .schemas import (
    AssignmentSchema,
    OverdueAssignmentItem,
    OverdueAssignmentListResponse,
)


def _to_overdue_schema(assignment: EquipmentAssignment) -> AssignmentSchema:
    """Inline conversion (avoids the services->assignment_service
    circular import during app startup) — pulls everything we need
    from the already-selected item + checkout_location relationships."""
    item = getattr(assignment, 'item', None)
    location = getattr(assignment, 'checkout_location', None)
    partner = getattr(assignment, 'assignee_partner', None)
    holder = holder_of_assignment(assignment)
    serial, asset_tag = unit_identifiers(item)
    return AssignmentSchema(
        id=assignment.id,
        item_id=assignment.item_id,
        item_name=(item.name if item is not None else ''),
        item_serial=serial,
        item_asset_tag=asset_tag,
        assignee_partner_id=assignment.assignee_partner_id,
        partner_name=(partner.name if partner is not None else None),
        checkout_location_id=assignment.checkout_location_id,
        checkout_location_name=(location.name if location is not None else None),
        assigned_to_name=assignment.assigned_to_name,
        assigned_to_email=assignment.assigned_to_email,
        holder_name=holder.name if holder is not None else None,
        holder_kind=holder.kind if holder is not None else None,
        checked_out_at=assignment.checked_out_at,
        expected_return_at=assignment.expected_return_at,
        checked_in_at=assignment.checked_in_at,
        checked_out_by=assignment.checked_out_by,
        checked_in_by=assignment.checked_in_by,
        checkout_notes=assignment.checkout_notes,
        checkin_notes=assignment.checkin_notes,
        checkin_condition=assignment.checkin_condition,
        created_at=assignment.created_at,
    )


async def list_overdue_assignments(
    db: AsyncSession,
    org_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> OverdueAssignmentListResponse:
    """Return paginated assignments whose return date has passed."""
    now = datetime.now(UTC)
    base = (
        select(EquipmentAssignment)
        .options(
            selectinload(EquipmentAssignment.item),
            selectinload(EquipmentAssignment.assignee_partner),
            selectinload(EquipmentAssignment.checkout_location),
        )
        .where(
            EquipmentAssignment.organization_id == org_id,
            EquipmentAssignment.checked_in_at.is_(None),
            EquipmentAssignment.expected_return_at.is_not(None),
            EquipmentAssignment.expected_return_at < now,
        )
        .order_by(EquipmentAssignment.expected_return_at.asc())
    )

    rows, total = await paginate_async(db, base, limit=limit, offset=offset)

    items: list[OverdueAssignmentItem] = []
    for row in rows:
        full = _to_overdue_schema(row)
        if row.expected_return_at is None:
            continue
        days_overdue = max(0, (now - row.expected_return_at).days)
        # ``row.item`` is the lazy-loaded relationship; use ``getattr`` so ruff
        # does not require the equipment module to import ``app.models``.
        item_row = getattr(row, 'item', None)
        items.append(
            OverdueAssignmentItem(
                assignment_id=full.id,
                item_id=full.item_id,
                item_name=full.item_name,
                item_barcode=(getattr(item_row, 'barcode', None) if item_row else None),
                item_serial=full.item_serial,
                item_asset_tag=full.item_asset_tag,
                holder_name=full.holder_name,
                holder_kind=full.holder_kind,
                assigned_to_email=full.assigned_to_email,
                checked_out_at=full.checked_out_at,
                expected_return_at=row.expected_return_at,
                days_overdue=days_overdue,
            )
        )

    return OverdueAssignmentListResponse.from_slice(
        items=items, offset=offset, limit=limit, total=total
    )
