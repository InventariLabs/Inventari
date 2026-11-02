"""Equipment dashboard and warranty analytics — read-only."""

# architecture: allow_direct_db_access
# reason: open-assignment counts joined against Core items need is_deleted and category filters CoreAPI cannot express

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.core.contracts import CategoryDTO, ItemDTO
from app.core.datetimes import parse_iso_date
from app.core.module_ownership import claimed_by_module
from app.core.module_scope import get_context_tags_of
from app.core.public_api import core_api
from app.models.item import Item

from ._holder import holder_of_assignment
from .models import EquipmentAssignment
from .schemas import (
    ByCategory,
    EquipmentDashboard,
    RecentActivityItem,
    WarrantyAlert,
)

# Hard cap for dashboard aggregation — dashboards aggregate org-wide,
# pagination does not apply; 10k covers all realistic equipment deployments.
_MAX_EQUIPMENT_ITEMS = 10000


def _claimed_equipment() -> ColumnElement[bool]:
    """The one answer to "is this record equipment", as a SQL predicate.

    Every reader here — the tiles, the assignment count — asks the same core
    predicate the asset list asks; a reader that answered from the category
    column alone disagreed with the list about an asset filed under no
    category, which the equipment form never required.
    """
    return claimed_by_module('equipment', get_context_tags_of('equipment'))


async def _get_equipment_items_and_categories_async(
    db: AsyncSession, org_id: UUID
) -> tuple[list[ItemDTO], dict[UUID, CategoryDTO]]:
    categories = await core_api.categories.list_async(db, org_id)
    cat_by_id = {c.id: c for c in categories}
    # the cap has to apply to equipment, not to the organisation's
    # items as a whole. Fetching a page of everything and filtering it down
    # afterwards left a fleet sitting behind enough newer non-equipment items
    # entirely absent — "0 Total Assets" beside "7 Checked Out".
    equipment_items = await core_api.items.list_async(
        db, org_id, context_tag='equipment', limit=_MAX_EQUIPMENT_ITEMS
    )
    return equipment_items, cat_by_id


async def get_dashboard(db: AsyncSession, org_id: UUID) -> EquipmentDashboard:
    eq_items, cat_by_id = await _get_equipment_items_and_categories_async(db, org_id)

    # Counted, not measured off the fetched page: the assignment count below is
    # a COUNT with no cap, and the two tiles have to answer for the same
    # population or they contradict each other on a fleet past the cap.
    #
    # Scoped through Item.organization_id, exactly as the assignment count
    # below is. CoreAPI's count reaches the organisation through an inner join
    # on StorageLocation instead; `items.storage_location_id` is NOT NULL, so
    # the two agree today, but only by way of a column neither tile is about.
    total_assets = (
        await db.scalar(
            select(func.count())
            .select_from(Item)
            .where(
                Item.organization_id == org_id,
                Item.is_deleted.is_(False),
                _claimed_equipment(),
            )
        )
    ) or 0
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}

    # An asset with an open assignment is counted once —
    # as issued. Without this, a maintenance entry on a checked-out asset
    # made the MAINTENANCE and "checked out" tiles overlap.
    open_item_ids = set(
        (
            await db.execute(
                select(EquipmentAssignment.item_id).where(
                    EquipmentAssignment.organization_id == org_id,
                    EquipmentAssignment.checked_in_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )

    for item in eq_items:
        eq_ns = (item.meta_data or {}).get('equipment', {})
        status_val = eq_ns.get('equipment_status', 'UNKNOWN')
        # RETIRED joins MAINTENANCE here: retiring a checked-out asset is
        # refused since, but rows written before that guard existed
        # would otherwise be counted in two tiles at once.
        if status_val in ('MAINTENANCE', 'RETIRED') and item.id in open_item_ids:
            status_val = 'DEPLOYED'
        by_status[status_val] = by_status.get(status_val, 0) + 1

        cat = cat_by_id.get(item.category_id) if item.category_id else None
        cat_code = cat.code if cat and cat.code else 'UNKNOWN'
        by_category[cat_code] = by_category.get(cat_code, 0) + 1

    # Assignment counts and the recent list must only
    # consider assignments of live equipment items — soft-deleted assets
    # (or assets outside the module's claim) left ghost rows behind.
    live_assignment_filter = (
        EquipmentAssignment.organization_id == org_id,
        EquipmentAssignment.checked_in_at.is_(None),
        Item.is_deleted.is_(False),
        _claimed_equipment(),
    )

    active_result = await db.execute(
        select(func.count())
        .select_from(EquipmentAssignment)
        .join(Item, EquipmentAssignment.item_id == Item.id)
        .where(*live_assignment_filter)
    )
    active_assignments_count = active_result.scalar() or 0

    warranty_alerts = await get_warranty_alerts(
        db,
        org_id,
        days=await warranty_horizon_days(db, org_id),
        items=eq_items,
        cat_by_id=cat_by_id,
    )
    expired_warranty_alerts = await get_expired_warranty_alerts(
        db, org_id, items=eq_items, cat_by_id=cat_by_id
    )

    recent_result = await db.execute(
        select(EquipmentAssignment)
        .options(
            selectinload(EquipmentAssignment.item),
            selectinload(EquipmentAssignment.assignee_partner),
            selectinload(EquipmentAssignment.checkout_location),
        )
        .join(Item, EquipmentAssignment.item_id == Item.id)
        .where(*live_assignment_filter)
        .order_by(EquipmentAssignment.checked_out_at.desc())
        .limit(5)
    )
    recent_assignments = list(recent_result.scalars().all())

    def _assignment_item_name(a: Any) -> str:
        return a.item.name if a.item else ''

    return EquipmentDashboard(
        total_assets=total_assets,
        active_assignments=active_assignments_count,
        in_maintenance=by_status.get('MAINTENANCE', 0),
        retired=by_status.get('RETIRED', 0),
        by_status=by_status,
        by_category=[
            ByCategory(category_name=code, count=cnt)
            for code, cnt in by_category.items()
        ],
        recent_activity=[
            RecentActivityItem(
                item_name=_assignment_item_name(a),
                action='CHECKOUT' if a.checked_in_at is None else 'CHECKIN',
                timestamp=a.checked_out_at.isoformat(),
            )
            for a in recent_assignments
        ],
        warranty_alerts=warranty_alerts,
        expired_warranty_alerts=expired_warranty_alerts,
    )


def _warranty_date(item: ItemDTO) -> date | None:
    """Parse ``meta_data.equipment.warranty_until``; None when absent/invalid."""
    raw = ((item.meta_data or {}).get('equipment', {})).get('warranty_until')
    if isinstance(raw, date):
        return raw
    return parse_iso_date(str(raw)) if raw else None


async def _assignees_for(
    db: AsyncSession, org_id: UUID, item_ids: list[UUID]
) -> dict[UUID, str]:
    """Open-assignment holder per item id — one batch for the whole section.

    The placeholder next to a warranty date answers "who or what holds it",
    the same question the overdue row asks, so it reads the module's one
    definition: a person's name, or the place a deployment stands in. The
    item relationship is not loaded — nothing here names the asset itself.
    """
    if not item_ids:
        return {}
    result = await db.execute(
        select(EquipmentAssignment)
        .options(noload(EquipmentAssignment.item))
        .where(
            EquipmentAssignment.organization_id == org_id,
            EquipmentAssignment.item_id.in_(item_ids),
            EquipmentAssignment.checked_in_at.is_(None),
        )
    )
    holders: dict[UUID, str] = {}
    for assignment in result.scalars().all():
        holder = holder_of_assignment(assignment)
        if holder is not None:
            holders[assignment.item_id] = holder.name
    return holders


def _to_alert(
    item: ItemDTO,
    warranty_date: date,
    today: date,
    cat_by_id: dict[UUID, CategoryDTO],
    assigned_by_item: dict[UUID, str],
) -> WarrantyAlert:
    eq_ns = (item.meta_data or {}).get('equipment', {})
    cat = cat_by_id.get(item.category_id) if item.category_id else None
    return WarrantyAlert(
        item_id=item.id,
        item_name=item.name,
        category_code=cat.code if cat and cat.code else '',
        serial_number=item.serial_number or eq_ns.get('serial_number'),
        warranty_until=warranty_date,
        days_remaining=(warranty_date - today).days,
        assigned_to=assigned_by_item.get(item.id),
    )


async def warranty_horizon_days(db: AsyncSession, org_id: UUID) -> int:
    """How far ahead an ending warranty is worth a word, by the module's settings."""
    settings = await core_api.settings.get_async(db, org_id, 'equipment') or {}
    return int(settings.get('warranty_warning_days', 30))


async def get_warranty_alerts(
    db: AsyncSession,
    org_id: UUID,
    days: int = 30,
    *,
    items: list[ItemDTO] | None = None,
    cat_by_id: dict[UUID, CategoryDTO] | None = None,
) -> list[WarrantyAlert]:
    """Items with warranty expiring within ``days`` and their active assignee.

       ``items``/``cat_by_id`` may be passed by callers that already fetched
       the fleet (e.g. :func:`get_dashboard`) so the list is not fetched twice.
       Assignments are resolved with a single batch query instead of one query
    per candidate.
    """
    today = await core_api.organizations.today_async(db, org_id)
    window = today + timedelta(days=days)

    if items is None or cat_by_id is None:
        items, cat_by_id = await _get_equipment_items_and_categories_async(db, org_id)

    candidates = [
        (item, warranty)
        for item in items
        if (warranty := _warranty_date(item)) and today <= warranty <= window
    ]
    assigned_by_item = await _assignees_for(
        db, org_id, [item.id for item, _ in candidates]
    )

    alerts = [
        _to_alert(item, warranty, today, cat_by_id, assigned_by_item)
        for item, warranty in candidates
    ]

    alerts.sort(key=lambda a: a.days_remaining)
    return alerts


async def get_expired_warranty_alerts(
    db: AsyncSession,
    org_id: UUID,
    *,
    items: list[ItemDTO] | None = None,
    cat_by_id: dict[UUID, CategoryDTO] | None = None,
) -> list[WarrantyAlert]:
    """Warranties that already lapsed.

       Sorted oldest expiry first — for an IT manager, "already without
       warranty" matters more than "expires in 21 days".

       Takes the same prefetch/batch route as :func:`get_warranty_alerts`: the
       caller can hand over the fleet it already loaded, and holders come from
       one query for the whole section rather than one per expired asset
    (follow-up, audit 2026-08-16).
    """
    today = await core_api.organizations.today_async(db, org_id)

    if items is None or cat_by_id is None:
        items, cat_by_id = await _get_equipment_items_and_categories_async(db, org_id)

    candidates = [
        (item, warranty)
        for item in items
        if (warranty := _warranty_date(item)) and warranty < today
    ]
    assigned_by_item = await _assignees_for(
        db, org_id, [item.id for item, _ in candidates]
    )

    alerts = [
        _to_alert(item, warranty, today, cat_by_id, assigned_by_item)
        for item, warranty in candidates
    ]

    alerts.sort(key=lambda a: a.warranty_until)
    return alerts
