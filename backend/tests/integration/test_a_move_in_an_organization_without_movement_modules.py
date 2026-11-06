"""Moving a record is recorded in the ledger whatever modules the organization runs.

Every organization records its stock movements; the modules only decide
whether the organization is *offered* the screens that read them. A quantity
change posts a movement without asking which modules are on, and the
relocation behind a record's shelf edit must answer the same way: an
organization with nothing but the core still has stock on its shelves and
still needs the shelf and the ledger to agree after a record is carried.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.schemas.item import ItemUpdate
from app.services.items import update_item
from tests.integration._core_api_helpers import make_template, make_user_context
from tests.integration._shelf import put_on_shelf


@pytest.mark.integration
@pytest.mark.asyncio
async def test_carrying_a_record_posts_one_move_with_no_movement_module(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location: StorageLocation,
    async_test_user,
):
    db = real_async_db_session
    org_id = async_test_household.id
    org = await db.get(Organization, org_id)
    assert org is not None
    org.enabled_modules = ['core', 'items']
    await db.flush()

    template = await db.run_sync(lambda s: make_template(s, org_id, name='Basil'))
    record = await put_on_shelf(
        db, async_test_user, template, async_test_storage_location.id, 4
    )
    target = StorageLocation(
        organization_id=org_id, name='Other shelf', created_by=async_test_user.id
    )
    db.add(target)
    await db.flush()

    await update_item(
        db,
        record,
        ItemUpdate(location_id=target.id),
        make_user_context(org_id, async_test_user.id),
    )

    carried = (
        await db.scalars(
            select(StockMove).where(
                StockMove.organization_id == org_id,
                StockMove.product_template_id == template.id,
                StockMove.from_location_id == async_test_storage_location.id,
                StockMove.to_location_id == target.id,
            )
        )
    ).all()
    assert len(carried) == 1, 'the carry left no single move in the ledger'
    assert carried[0].quantity == Decimal('4')
    assert record.storage_location_id == target.id
