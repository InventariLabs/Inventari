# architecture: allow_direct_db_access
# reason: JSONB meta_data and open-assignment filters are not expressible through CoreAPI list_async

"""Server-side filtering for the equipment asset list.

Core ``GET /items`` cannot filter by ``meta_data.equipment.equipment_status``
nor by "has an open assignment", which made the Overview tile (counts open
``EquipmentAssignment`` rows) and the asset list (client-side filter over one
page) disagree. This module-level endpoint adds both filters; the
assignment table is the source of truth for "checked out".
"""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.core.db_utils import escape_ilike, paginate_async
from app.core.module_ownership import claimed_by_module, standing_location
from app.core.module_scope import get_context_tags_of
from app.models.item import Item

from ._holder import Holder, holder_of_assignment
from .models import EquipmentAssignment

# sortable keys for the asset list. `warranty_until` lives in the
# equipment meta_data namespace; `location` orders by the storage location
# name and requires an outerjoin, so it is handled separately.
_SORT_KEYS = ('name', 'created_at', 'purchase_price', 'warranty_until', 'location')


def open_placements(org_id: UUID) -> Select[tuple[UUID, UUID | None]]:
    """The org's assets checked out to a place, and the place, while it lasts.

    Registered with Core (``register_record_placement``), so the list, its
    location filter and sort, and the locations screen's counts all say an
    asset stands where the Location column says it does. One row per asset:
    an asset has at most one open assignment.
    """
    return select(
        EquipmentAssignment.item_id, EquipmentAssignment.checkout_location_id
    ).where(
        EquipmentAssignment.organization_id == org_id,
        EquipmentAssignment.checked_in_at.is_(None),
        EquipmentAssignment.checkout_location_id.is_not(None),
    )


def _asset_filters(
    org_id: UUID,
    *,
    search: str | None,
    category_id: UUID | None,
    storage_id: UUID | None,
    status: str | None,
    checked_out: bool,
) -> list[ColumnElement[bool]]:
    """The WHERE clauses of the asset list, shared with the bulk-by-filter path.

    "Is this record equipment" is asked of the core, in the same predicate
    that lists this module's locations and counts the assets standing in
    them. This list used to answer it on its own — the ``meta_data``
    namespace or a category tagged ``equipment`` — and the two answers
    disagreed in both directions: a location row promising one asset opened
    a list with none, and a location holding an asset the list could show
    had no count and no link at all. Both are promises the reader can check
    against each other, so there is one answer to check.
    """
    clauses: list[ColumnElement[bool]] = [
        Item.organization_id == org_id,
        Item.is_deleted.is_(False),
        claimed_by_module('equipment', get_context_tags_of('equipment')),
    ]
    if storage_id is not None:
        # Where the list says an asset is: the place it is checked out to
        # while it stands there, its own location otherwise — so a place's
        # filter finds what the rows say stands in it.
        clauses.append(standing_location('equipment', org_id) == storage_id)
    if category_id is not None:
        clauses.append(Item.category_id == category_id)
    if search:
        pattern = f'%{escape_ilike(search)}%'
        clauses.append(
            Item.name.ilike(pattern)
            | Item.brand.ilike(pattern)
            | Item.barcode.ilike(pattern)
            | Item.label_code.ilike(pattern)
            # Serial number / asset tag live in the
            # equipment meta_data namespace (plus the core column filled
            # by other paths) — the most common lookup in this domain.
            | Item.serial_number.ilike(pattern)
            | Item.meta_data['equipment']['serial_number'].astext.ilike(pattern)
            | Item.meta_data['equipment']['asset_tag'].astext.ilike(pattern)
        )
    if status is not None:
        clauses.append(Item.meta_data['equipment']['equipment_status'].astext == status)
    if checked_out:
        clauses.append(
            Item.id.in_(
                select(EquipmentAssignment.item_id).where(
                    EquipmentAssignment.organization_id == org_id,
                    EquipmentAssignment.checked_in_at.is_(None),
                )
            )
        )
    return clauses


async def list_matching_asset_ids_async(
    db: AsyncSession,
    org_id: UUID,
    *,
    search: str | None = None,
    category_id: UUID | None = None,
    location_id: UUID | None = None,
    status: str | None = None,
    checked_out: bool = False,
) -> list[UUID]:
    """Every asset id the list's filters match — the scope of a bulk action.

    Ids only, without a page: the caller decides whether the count is one it
    is willing to walk in a single request. The keywords are the list's
    filters as the request names them (``AssetFilter``).
    """
    clauses = _asset_filters(
        org_id,
        search=search,
        category_id=category_id,
        storage_id=location_id,
        status=status,
        checked_out=checked_out,
    )
    rows = await db.execute(select(Item.id).where(*clauses))
    return list(rows.scalars().all())


async def list_equipment_assets_async(
    db: AsyncSession,
    org_id: UUID,
    *,
    search: str | None = None,
    category_id: UUID | None = None,
    storage_id: UUID | None = None,
    status: str | None = None,
    checked_out: bool = False,
    sort: str | None = None,
    sort_dir: str = 'desc',
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Item], int, dict[UUID, Holder]]:
    """List the org's equipment assets.

    Mirrors the Core listing semantics (non-deleted, eager-loaded relations,
    ILIKE search over name/brand/barcode/label_code, ``created_at`` desc)
    plus the two filters CoreAPI cannot express.
    """
    clauses = _asset_filters(
        org_id,
        search=search,
        category_id=category_id,
        storage_id=storage_id,
        status=status,
        checked_out=checked_out,
    )
    query = (
        select(Item)
        .options(
            selectinload(Item.category),
            selectinload(Item.storage_location),
            selectinload(Item.uom),
            selectinload(Item.template),
        )
        .where(*clauses)
    )

    if sort not in _SORT_KEYS or sort is None:
        query = query.order_by(Item.created_at.desc())
    elif sort == 'location':
        # By the name the Location column prints — the place an asset is
        # checked out to while it stands there, not the home it returns to.
        # Nullable for safety: an asset without a location sorts last in
        # both directions rather than disappearing between the two ends.
        location = Item.storage_location.property.mapper.class_
        ordering = (
            location.name.asc().nulls_last()
            if sort_dir == 'asc'
            else location.name.desc().nulls_last()
        )
        query = query.outerjoin(
            location, location.id == standing_location('equipment', org_id)
        ).order_by(ordering)
    else:
        column = {
            'name': Item.name,
            'created_at': Item.created_at,
            'purchase_price': Item.purchase_price,
            'warranty_until': Item.meta_data['equipment']['warranty_until'].astext,
        }[sort]
        ordering = (
            column.asc().nulls_last()
            if sort_dir == 'asc'
            else column.desc().nulls_last()
        )
        query = query.order_by(ordering)

    rows, total = await paginate_async(db, query, limit=limit, offset=offset)
    items = list(rows)

    # one batched query for open assignments (never one per row); the place
    # a deployment stands in rides the row's selectin relationship, so the
    # holder is resolved here, once. The map is returned alongside the page —
    # the router attaches it to the payload DTOs, so no ORM rows are mutated
    # after the select.
    assigned: dict[UUID, Holder] = {}
    if items:
        assign_rows = (
            (
                await db.execute(
                    select(EquipmentAssignment).where(
                        EquipmentAssignment.organization_id == org_id,
                        EquipmentAssignment.item_id.in_([i.id for i in items]),
                        EquipmentAssignment.checked_in_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for assignment in assign_rows:
            holder = holder_of_assignment(assignment)
            if holder is not None:
                assigned[assignment.item_id] = holder

    return items, total, assigned
