"""One definition of "expired", shared by every count that shows it.

The overview tile counted `expiry_date <= today` while the list behind it
counted `expiry_date < today`, so an item best-before today appeared in the
tile and not in the list it opened — 64 against 63.

"Best before 15.08" means 15.08 is still fine, so the list was right: an item
whose expiry date is today is *expiring soon*, not expired.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.models.item import Item
from app.services.items._query_get import get_items

pytestmark = pytest.mark.integration


async def _make_item(
    db: AsyncSession,
    org_id,
    storage_id,
    *,
    name: str,
    expiry_date: date | None = None,
) -> Item:
    item = Item(
        organization_id=org_id,
        storage_location_id=storage_id,
        name=name,
        quantity=Decimal('1'),
        expiry_date=expiry_date,
    )
    db.add(item)
    await db.flush()
    return item


@pytest.mark.asyncio
class TestExpiryPredicate:
    async def test_item_expiring_today_is_not_expired_in_either_path(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """The overview tile and the list it opens count the same items."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id
        today = date.today()

        await _make_item(
            db, org_id, loc_id, name='Best before today', expiry_date=today
        )
        await _make_item(
            db,
            org_id,
            loc_id,
            name='Already expired',
            expiry_date=today - timedelta(days=1),
        )
        await db.commit()

        overview = await core_api.queries.get_overview_async(db, org_id)

        listed, total = await db.run_sync(
            lambda s: get_items(
                db=s,
                organization_id=org_id,
                only_expired=True,
            )
        )

        assert overview.expired == 1
        assert total == overview.expired
        assert [i.name for i in listed] == ['Already expired']

    async def test_expiring_list_matches_the_tile_it_opens(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """The expiring list had a horizon but no floor, so it also showed
        items whose date had already passed — the tile said 2, the list 3."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id
        today = date.today()

        await _make_item(
            db, org_id, loc_id, name='Best before today', expiry_date=today
        )
        await _make_item(
            db,
            org_id,
            loc_id,
            name='Best before Friday',
            expiry_date=today + timedelta(days=3),
        )
        await _make_item(
            db,
            org_id,
            loc_id,
            name='Already expired',
            expiry_date=today - timedelta(days=1),
        )
        await db.commit()

        overview = await core_api.queries.get_overview_async(db, org_id)

        listed, total = await db.run_sync(
            lambda s: get_items(
                db=s,
                organization_id=org_id,
                expiring_days=7,
            )
        )

        assert total == overview.expiring_soon
        assert sorted(i.name for i in listed) == [
            'Best before Friday',
            'Best before today',
        ]

    async def test_item_expiring_today_counts_as_expiring_soon(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """It must land in a bucket, not fall out of both."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id

        await _make_item(
            db, org_id, loc_id, name='Best before today', expiry_date=date.today()
        )
        await db.commit()

        overview = await core_api.queries.get_overview_async(db, org_id)

        assert overview.expired == 0
        assert overview.expiring_soon == 1
