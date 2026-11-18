"""Three readers of "expires within N days", one window.

The storage detail summary, the storages list and the items list each
had a window of their own. The list and the counter agreed on the floor;
the detail summary had none, so a shelf holding one item that expired last
month reported it as expiring soon — while the same item was already
counted as expired on the dashboard beside it.

The window is ``items.expiry.is_expiring_soon``: from the organization's
today, inclusive, to today + N, inclusive. Anything earlier is expired,
which is a bucket of its own and not this one.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.services.items._query_get import _apply_item_filters
from app.services.items.expiry import expiry_today_async
from app.services.storage._queries import (
    count_expiring_soon_async,
    expiring_counts_by_location_async,
)

DAYS = 7


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheExpiringWindowIsOneWindow:
    async def _seed_the_four_corners(
        self, db: AsyncSession, org: Organization, storage, category
    ) -> dict[str, Item]:
        """One item on each side of both edges of the window."""
        today = await expiry_today_async(db, org.id)
        offsets = {
            'yesterday': today - timedelta(days=1),
            'today': today,
            'last day': today + timedelta(days=DAYS),
            'day after': today + timedelta(days=DAYS + 1),
        }
        items = {
            label: Item(
                organization_id=org.id,
                storage_location_id=storage.id,
                category_id=category.id,
                name=f'Corner {label}',
                quantity=1,
                expiry_date=when,
            )
            for label, when in offsets.items()
        }
        db.add_all(list(items.values()))
        await db.flush()
        return items

    async def test_all_three_readers_see_the_same_two_items(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location,
        async_test_category,
    ) -> None:
        db = real_async_db_session
        items = await self._seed_the_four_corners(
            db, async_test_household, async_test_storage_location, async_test_category
        )

        # The items list's own filter, which is what `expiring_days=` asks for.
        listed = set(
            (
                await db.execute(
                    _apply_item_filters(
                        select(Item.id).join(
                            StorageLocation,
                            Item.storage_location_id == StorageLocation.id,
                        ),
                        organization_id=async_test_household.id,
                        expiring_days=DAYS,
                        today=await expiry_today_async(db, async_test_household.id),
                    )
                )
            ).scalars()
        )
        assert items['today'].id in listed
        assert items['last day'].id in listed
        assert items['yesterday'].id not in listed, 'expired is its own bucket'
        assert items['day after'].id not in listed, 'past the horizon'

        detail_count = await count_expiring_soon_async(
            db,
            async_test_household.id,
            async_test_storage_location.id,
            days=DAYS,
        )
        list_counts = await expiring_counts_by_location_async(
            db,
            async_test_household.id,
            [async_test_storage_location.id],
            days=DAYS,
        )

        assert detail_count == len(listed) == 2
        assert list_counts.get(async_test_storage_location.id) == detail_count

    async def test_an_expired_item_alone_on_a_shelf_counts_nowhere_here(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location,
        async_test_category,
    ) -> None:
        """The storage summary answers this case the same way as the expiring window."""
        db = real_async_db_session
        today = await expiry_today_async(db, async_test_household.id)
        db.add(
            Item(
                organization_id=async_test_household.id,
                storage_location_id=async_test_storage_location.id,
                category_id=async_test_category.id,
                name='Long gone',
                quantity=1,
                expiry_date=today - timedelta(days=30),
            )
        )
        await db.flush()

        detail_count = await count_expiring_soon_async(
            db,
            async_test_household.id,
            async_test_storage_location.id,
            days=DAYS,
        )
        list_counts = await expiring_counts_by_location_async(
            db,
            async_test_household.id,
            [async_test_storage_location.id],
            days=DAYS,
        )

        assert detail_count == 0
        assert list_counts.get(async_test_storage_location.id, 0) == 0
