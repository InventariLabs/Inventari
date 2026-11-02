"""A record with a product stands in a group that has an anchor.

The anchor protects a group of stock only if every write to the group locks
it, and the lock is what creates a missing anchor. A door that put a record
into a group nobody had stocked, without the lock, wrote stock that no lock
covered — and nothing showed it. The records now carry a foreign key to
their group's anchor, so that door fails loudly instead.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.models.item import Item
from app.models.stock_anchor import StockAnchor

from ._core_api_helpers import make_template
from ._shelf import put_on_shelf, shelf_keeper

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _template(db: AsyncSession, org_id: uuid.UUID):
    return await db.run_sync(
        lambda s: make_template(s, org_id, name=f'Beans {uuid.uuid4().hex[:6]}')
    )


def _record(org_id, template_id, location_id) -> Item:
    return Item(
        organization_id=org_id,
        template_id=template_id,
        storage_location_id=location_id,
        name='Written past the lock',
        quantity=Decimal('3'),
    )


async def test_a_record_written_into_a_new_group_without_the_lock_is_refused(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    template = await _template(db, org_id)

    db.add(_record(org_id, template.id, async_test_storage_location.id))
    with pytest.raises(IntegrityError, match='fk_items_stock_anchor'):
        await db.flush()


async def test_the_same_record_written_after_the_lock_stands(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    template = await _template(db, org_id)

    await core_api.stock.lock_async(
        db, org_id, keys=[(template.id, async_test_storage_location.id)]
    )
    db.add(_record(org_id, template.id, async_test_storage_location.id))
    await db.flush()


async def test_a_record_without_a_product_needs_no_anchor(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id

    db.add(_record(org_id, None, async_test_storage_location.id))
    await db.flush()


async def test_a_record_created_through_the_items_service_brings_its_anchor(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    template = await _template(db, org_id)
    keeper = await shelf_keeper(db, org_id)

    await put_on_shelf(db, keeper, template, async_test_storage_location.id, 4)

    anchors = await db.scalar(
        select(func.count())
        .select_from(StockAnchor)
        .where(
            StockAnchor.organization_id == org_id,
            StockAnchor.product_template_id == template.id,
            StockAnchor.storage_location_id == async_test_storage_location.id,
        )
    )
    assert anchors == 1
