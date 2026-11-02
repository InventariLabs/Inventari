# architecture: allow_direct_db_access
# reason: duplicate detection by equipment JSONB serial number cannot be expressed through CoreAPI list_async

"""Serial-number duplicate lookup for the equipment import.

Kept separate from ``import_service.py`` so the escape-hatch file stays
read-only (it performs no commits) while the import service keeps its
CoreAPI-only write path.
"""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item


async def find_item_by_serial_async(
    db: AsyncSession, org_id: UUID, serial_number: str
) -> Item | None:
    """Find a live item by its equipment serial number within the org.

    Looks in both places: the core column every write path now fills, and
    the equipment namespace where rows created before the consolidation
    kept it. Matching only the column would let a re-import create a second
    copy of an asset that is already there.
    """
    result = await db.execute(
        select(Item).where(
            Item.organization_id == org_id,
            Item.is_deleted.is_(False),
            or_(
                Item.serial_number == serial_number,
                Item.meta_data['equipment']['serial_number'].astext == serial_number,
            ),
        )
    )
    return result.scalars().first()
