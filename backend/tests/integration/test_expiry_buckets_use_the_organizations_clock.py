"""The expiry horizon counts from the organization's day, not the server's.

The report helpers learned this first (see
``test_reports_use_the_organizations_clock.py``); the item buckets had not.
An item "expiring within 7 days" means seven days from the reader's today —
and an organization a few hours east or west of UTC stands on a different
date than the server, so the boundary item changes buckets.

The zone is chosen at runtime so the org's local date provably differs from
the server's (UTC) date whatever hour the suite runs at: zones span
UTC−12…UTC+14, so east of +10 the local day has already tipped over, and
west of −10 it has not yet.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.services.analytics._common import org_today_async
from app.services.items._query_special import get_expiring_items_async
from app.services.storage._queries import (
    count_expiring_soon_async,
    expiring_counts_by_location_async,
)


def _zone_whose_local_day_differs_from_utc(now_utc_hour: int) -> str:
    if now_utc_hour >= 10:
        # UTC+14: the local day has already tipped into tomorrow.
        return 'Etc/GMT-14'
    # UTC−12: the local day is still yesterday.
    return 'Etc/GMT+12'


def _org_zone() -> str:
    """A zone whose local date differs from the server's (UTC) date now."""
    return _zone_whose_local_day_differs_from_utc(datetime.now(UTC).hour)


@pytest.mark.integration
@pytest.mark.asyncio
class TestExpiryBucketsUseTheOrganizationsClock:
    async def _ahead_org_day(
        self, db: AsyncSession, org: Organization
    ) -> tuple[date, bool]:
        """Set the org's zone so its day differs from the server's day."""
        org.timezone = _org_zone()
        await db.flush()
        org_today = await org_today_async(db, org.id)
        assert org_today != date.today(), 'zone trick failed — pick another zone'
        return org_today, org_today > date.today()

    async def test_expiring_horizon_ends_on_the_orgs_day(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location,
        async_test_category,
    ) -> None:
        """The item sitting exactly on the server's horizon lands where the
        org's clock puts it, not where the server's does."""
        db = real_async_db_session
        org = async_test_household
        org_today, org_is_ahead = await self._ahead_org_day(db, org)

        utc_today = date.today()
        probe = Item(
            organization_id=org.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Horizon Probe',
            quantity=1,
            # Exactly on the server-clock horizon (inclusive) — the server
            # would always list it; the org's clock decides for real.
            expiry_date=utc_today + timedelta(days=7),
        )
        control = Item(
            organization_id=org.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Horizon Control',
            quantity=1,
            expiry_date=org_today + timedelta(days=1),
        )
        db.add_all([probe, control])
        await db.flush()

        rows, _total = await get_expiring_items_async(
            db,
            [async_test_storage_location.id],
            organization_id=org.id,
            days=7,
        )
        ids = {row.id for row in rows}

        assert control.id in ids, 'control row must always be inside the horizon'
        assert (probe.id in ids) == org_is_ahead

    async def test_expiring_count_floors_at_the_orgs_day(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location,
        async_test_category,
    ) -> None:
        """Already-expired is measured against the org's today: an item the
        server calls expired can still be inside the org's window."""
        db = real_async_db_session
        org = async_test_household
        org_today, org_is_ahead = await self._ahead_org_day(db, org)

        utc_today = date.today()
        control = Item(
            organization_id=org.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Count Control',
            quantity=1,
            expiry_date=org_today + timedelta(days=1),
        )
        probe = Item(
            organization_id=org.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Count Probe',
            quantity=1,
            # The server's today: below the org's floor when the org is
            # ahead of UTC, inside it when the org is behind.
            expiry_date=utc_today,
        )
        db.add_all([control, probe])
        await db.flush()

        counts = await expiring_counts_by_location_async(
            db, org.id, [async_test_storage_location.id], days=7
        )

        expected = 2 if not org_is_ahead else 1
        assert counts.get(async_test_storage_location.id) == expected

    async def test_count_expiring_soon_reads_the_orgs_day(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location,
        async_test_category,
    ) -> None:
        db = real_async_db_session
        org = async_test_household
        org_today, _ = await self._ahead_org_day(db, org)

        item = Item(
            organization_id=org.id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Storage Count Probe',
            quantity=1,
            expiry_date=org_today + timedelta(days=1),
        )
        db.add(item)
        await db.flush()

        count = await count_expiring_soon_async(
            db, org.id, async_test_storage_location.id, days=7
        )
        assert count == 1


@pytest.mark.integration
class TestItemListUsesTheOrganizationsClock:
    def test_items_list_expiry_filter_cuts_on_the_orgs_day(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user,
        test_storage_location,
        test_category,
        db_session: Session,
    ) -> None:
        """GET /items?expiring_days=7 draws its horizon from the org zone."""
        from zoneinfo import ZoneInfo

        utc_today = date.today()
        org = db_session.get(Organization, test_user.organization_id)
        assert org is not None
        org.timezone = _org_zone()
        db_session.commit()

        org_today = datetime.now(ZoneInfo(org.timezone)).date()
        assert org_today != utc_today, 'zone trick failed — pick another zone'
        org_is_ahead = org_today > utc_today

        probe = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='List Horizon Probe',
            quantity=1,
            # Exactly on the server-clock horizon (inclusive) — the server
            # would always list it; the org's clock decides for real.
            expiry_date=utc_today + timedelta(days=7),
        )
        db_session.add(probe)
        db_session.commit()

        resp = client.get(
            '/api/v1/items',
            headers=auth_headers,
            params={'expiring_days': 7, 'limit': 100},
        )
        assert resp.status_code == 200, resp.text
        names = [row['name'] for row in resp.json()['items']]

        assert (probe.name in names) == org_is_ahead
