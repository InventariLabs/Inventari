"""The occupancy overview: every warehouse and shelf of the organization.

Mounted by ``warehouse/router.py``. One endpoint,
``GET /putaway/occupancy``, answers the whole screen in a fixed number of
queries however many locations there are: the locations, the limits, what
stands on each shelf, the product names and units, and the record counts —
each read once and joined in memory. The per-location read next to it
(``/putaway/occupancy/{location_id}``) stays for the readers that want one
subtree, and lists every product of a shelf the overview only counts.

The fill of a shelf is ``shelf_fill`` through ``_occupancy_cell``, the same
sum the putaway planner decides by. What this adds is the roll-up: a
location with others under it carries the counts of every shelf below it,
so the screen never adds up thousands of rows in the browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import StorageDTO, UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.module_scope import get_claimed_context_tags
from app.core.public_api import core_api

from ._router_capacity import _occupancy_cell
from ._shelf_fill import STATUS_EMPTY, STATUS_NEARLY_FULL, STATUS_OVER
from .models import PutawayCapacity
from .putaway_schemas import PutawayOccupancyOverview

router = APIRouter()

#: Locations of the organization's own floor. The virtual counterparts
#: (customers, production, inventory loss) are not places stock is shelved.
_FLOOR_USAGE = 'internal'
#: One query takes every location; a warehouse of tens of thousands of
#: shelves is the ceiling this screen is designed for.
_LOCATION_LIMIT = 100_000


@dataclass
class _Tally:
    """A running summary; ``fill_sum`` keeps the capped percentages."""

    shelves: int = 0
    with_limit: int = 0
    full: int = 0
    over: int = 0
    empty: int = 0
    fill_sum: int = 0

    def add_shelf(self, cell: dict[str, Any]) -> None:
        self.shelves += 1
        if cell['fill'] is not None:
            self.with_limit += 1
            self.fill_sum += min(cell['fill'], 100)
        if cell['status'] in (STATUS_NEARLY_FULL, STATUS_OVER):
            self.full += 1
        if cell['status'] == STATUS_OVER:
            self.over += 1
        if cell['status'] == STATUS_EMPTY:
            self.empty += 1

    def add(self, other: _Tally) -> None:
        self.shelves += other.shelves
        self.with_limit += other.with_limit
        self.full += other.full
        self.over += other.over
        self.empty += other.empty
        self.fill_sum += other.fill_sum

    def out(self) -> dict[str, Any]:
        return {
            'shelves': self.shelves,
            'with_limit': self.with_limit,
            'full': self.full,
            'over': self.over,
            'empty': self.empty,
            'average_fill': (
                round(self.fill_sum / self.with_limit) if self.with_limit else None
            ),
        }


def _walk_order(
    locations: list[StorageDTO],
) -> tuple[dict[UUID | None, list[StorageDTO]], list[StorageDTO]]:
    """Children by parent, each family in walk order, and the roots.

    A location whose parent is not among *locations* (archived, or a
    virtual one) is a root here: its own branch is still worth showing.
    """
    ids = {loc.id for loc in locations}
    children: dict[UUID | None, list[StorageDTO]] = {}
    for loc in locations:
        key = loc.parent_id if loc.parent_id in ids else None
        children.setdefault(key, []).append(loc)
    for family in children.values():
        family.sort(
            key=lambda loc: (
                loc.sequence is None,
                loc.sequence or 0,
                loc.name.lower(),
            )
        )
    return children, children.get(None, [])


async def _floor_locations(db: AsyncSession, org_id: UUID) -> list[StorageDTO]:
    """The organization's shelved locations, vertical-module places left out
    the way the location tree on the settings screens leaves them out."""
    claimed = get_claimed_context_tags()
    locations = await core_api.locations.list_async(
        db, org_id, usage=_FLOOR_USAGE, limit=_LOCATION_LIMIT
    )
    return [
        loc
        for loc in locations
        if not loc.context_tag or loc.context_tag not in claimed
    ]


@router.get('/putaway/occupancy', response_model=PutawayOccupancyOverview)
async def get_putaway_occupancy_overview(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Every location in walk order with its fill, and the roll-up above it.

    A shelf is a location with nothing under it, or one that holds stock or
    a limit itself — a location that holds others can hold goods too.
    A shelf's ``cell`` is its fill; a location with others under it carries
    a ``summary`` of the shelves below. ``totals`` is the same summary over
    the whole organization.
    """
    org_id = require_org(current_user)
    locations = await _floor_locations(db, org_id)
    scope = [loc.id for loc in locations]

    limits: dict[UUID, dict[UUID, Decimal]] = {}
    for entry in (
        (
            await db.execute(
                select(PutawayCapacity).where(PutawayCapacity.organization_id == org_id)
            )
        )
        .scalars()
        .all()
    ):
        limits.setdefault(entry.location_id, {})[entry.product_template_id] = (
            entry.max_quantity
        )

    # What a shelf holds, told per shelf: the limited products by name —
    # they make the fill — the one product of a shelf that holds one, and a
    # count of the rest. A floor of a hundred thousand products holds
    # hundreds of thousands of product groups; listing them all made this
    # answer tens of megabytes, and nobody reads them off a map.
    limited = {pid for shelf in limits.values() for pid in shelf}
    quantities: dict[UUID, dict[UUID, Decimal]] = {}
    unlisted: dict[UUID, int] = {}
    for contents in await core_api.stock.shelf_contents_async(db, org_id, limited):
        shelf = dict(contents.quantities)
        if contents.only_product_template_id is not None:
            shelf.setdefault(
                contents.only_product_template_id,
                contents.only_quantity or Decimal('0'),
            )
        quantities[contents.location_id] = shelf
        unlisted[contents.location_id] = contents.products - sum(
            1 for q in shelf.values() if q > 0
        )

    template_ids = sorted(
        limited | {pid for shelf in quantities.values() for pid in shelf}
    )
    templates = await core_api.product_templates.names_and_units_async(
        db, org_id, template_ids
    )
    template_names = {
        tid: (templates[tid][0] if tid in templates else '') for tid in template_ids
    }
    template_units = {
        tid: (templates[tid][1] if tid in templates else None) for tid in template_ids
    }
    item_counts = await core_api.locations.item_counts_by_location_async(
        db, org_id, scope
    )

    children, roots = _walk_order(locations)
    nodes: list[dict[str, Any]] = []
    totals = _Tally()

    def visit(loc: StorageDTO, depth: int) -> _Tally:
        family = children.get(loc.id, [])
        has_children = bool(family)
        own_stock = (
            bool(limits.get(loc.id))
            or unlisted.get(loc.id, 0) > 0
            or any(q > 0 for q in quantities.get(loc.id, {}).values())
        )
        node: dict[str, Any] = {
            'location_id': loc.id,
            'parent_id': loc.parent_id,
            'name': loc.name,
            'short_code': loc.short_code,
            'sequence': loc.sequence,
            'depth': depth,
            'has_children': has_children,
            'cell': None,
            'summary': None,
        }
        nodes.append(node)
        tally = _Tally()
        if not has_children or own_stock:
            cell = _occupancy_cell(
                location_id=loc.id,
                location_name=loc.name,
                quantities=quantities.get(loc.id, {}),
                limits=limits.get(loc.id, {}),
                template_names=template_names,
                items_count=item_counts.get(loc.id, 0),
                template_units=template_units,
                unlisted=unlisted.get(loc.id, 0),
            )
            node['cell'] = cell
            tally.add_shelf(cell)
        for child in family:
            tally.add(visit(child, depth + 1))
        if has_children:
            node['summary'] = tally.out()
        return tally

    for root in roots:
        totals.add(visit(root, 0))
    return {'nodes': nodes, 'totals': totals.out()}
