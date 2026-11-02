"""Item counts per storage are scoped to the reading organization.

The storage listing and the zones endpoint share one count helper whose SQL
said nothing about the organization, so a record another organization parked
in one of our locations (the write side does not validate that reference)
inflated our ``items_count``. The twin helpers in
``storage/_queries.py`` filter by organization — the two answers to the same
question disagreed.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.models.organization import Organization
from app.services.storage._queries import (
    count_items_in_location_async,
    expiring_counts_by_location_async,
    item_counts_by_location_async,
)


@pytest.mark.integration
@pytest.mark.asyncio
class TestStorageItemCountsTenancy:
    async def _foreign_org(self, db: AsyncSession) -> Organization:
        foreign_org = Organization(name='Foreign Organization', enabled_modules=[])
        db.add(foreign_org)
        await db.flush()
        return foreign_org

    async def test_foreign_items_stay_out_of_our_counts(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
        async_test_category,
    ) -> None:
        """A foreign organization's item referencing our location must not
        enter the organization's items_count."""
        db = real_async_db_session
        org = async_test_household
        foreign_org = await self._foreign_org(db)

        own = Item(
            organization_id=org.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Own Item',
            quantity=1,
        )
        foreign = Item(
            organization_id=foreign_org.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Foreign Item',
            quantity=1,
        )
        db.add_all([own, foreign])
        await db.flush()

        counts = await item_counts_by_location_async(
            db, org.id, [async_test_storage_location.id]
        )

        assert counts.get(async_test_storage_location.id) == 1

    async def test_expiring_counts_stay_out_of_foreign_items(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
        async_test_category,
    ) -> None:
        """The expiring bucket is the same drift: a foreign item about to
        expire in our location must not enter our expiring_soon_count."""
        db = real_async_db_session
        org = async_test_household
        foreign_org = await self._foreign_org(db)
        soon = date.today() + timedelta(days=3)

        own = Item(
            organization_id=org.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Own Expiring',
            quantity=1,
            expiry_date=soon,
        )
        foreign = Item(
            organization_id=foreign_org.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Foreign Expiring',
            quantity=1,
            expiry_date=soon,
        )
        db.add_all([own, foreign])
        await db.flush()

        expiring = await expiring_counts_by_location_async(
            db, org.id, [async_test_storage_location.id], days=7
        )

        assert expiring.get(async_test_storage_location.id) == 1

    async def test_counts_agree_with_the_location_twin(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
        async_test_category,
        async_test_item,
    ) -> None:
        """The listing count and the location twin answer identically on the
        same data — the drift that hid the tenant gap stays closed."""
        db = real_async_db_session
        org = async_test_household
        second = Item(
            organization_id=org.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Second Own Item',
            quantity=3,
        )
        db.add(second)
        await db.flush()

        counts = await item_counts_by_location_async(
            db, org.id, [async_test_storage_location.id]
        )
        twin = await count_items_in_location_async(
            db, org.id, async_test_storage_location.id
        )

        assert counts.get(async_test_storage_location.id) == 2
        assert twin == counts.get(async_test_storage_location.id)
