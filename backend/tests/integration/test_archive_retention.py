"""archive retention — periodic purge of long-archived items.

Orgs opt in via ``settings['archive_retention_days']``. The retention run
purges archived items older than the cutoff through the same path as manual
purge (blockers, org flag) with reason ``RETENTION`` and a null
user (system). Blocked items are reported, never retried within the run.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.organization import Organization
from app.modules.stock_takes.models import StockTake, StockTakeItem

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
class TestArchiveRetention:
    async def test_retention_purges_old_archived_items_with_audit_trail(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_item: Item,
    ) -> None:
        """Old archived item → purged; audit entry has RETENTION + null user."""
        from app.services.items._retention import run_archive_retention

        db = real_async_db_session
        now = datetime.now(UTC)
        async_test_household.settings = {'archive_retention_days': 1}
        async_test_item.is_deleted = True
        async_test_item.deleted_at = now - timedelta(days=5)
        async_test_item.deletion_reason = 'OTHER'
        await db.commit()

        report = await run_archive_retention(db, now=now)
        await db.commit()

        assert report.purged == 1
        assert report.blocked == []

        result = await db.execute(select(Item).where(Item.id == async_test_item.id))
        assert result.scalars().first() is None

        entry = (
            (
                await db.execute(
                    select(AuditLog).where(
                        AuditLog.target_type == 'item',
                        AuditLog.target_id == async_test_item.id,
                        AuditLog.action == 'PURGE',
                    )
                )
            )
            .scalars()
            .one()
        )
        assert entry.reason == 'RETENTION'
        assert entry.user_id is None

    async def test_blocked_item_is_reported_and_kept(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user,
        async_test_item: Item,
    ) -> None:
        """Item linked to a stock take → kept, reported as blocked."""
        from app.core.context import ModuleContext
        from app.core.events import event_bus
        from app.core.module_registry import module_registry
        from app.services.items._retention import run_archive_retention

        # No HTTP client in this test — wire module interceptors the way the
        # app lifespan does, so the stock_takes purge blocker is registered.
        stock_takes_module = module_registry.get('stock_takes')
        assert stock_takes_module is not None
        stock_takes_module.run_startup(
            ModuleContext(event_bus=event_bus, db=real_async_db_session)
        )

        db = real_async_db_session
        now = datetime.now(UTC)
        async_test_household.settings = {'archive_retention_days': 1}
        async_test_item.is_deleted = True
        async_test_item.deleted_at = now - timedelta(days=5)
        async_test_item.deletion_reason = 'OTHER'

        take = StockTake(
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            storage_location_id=async_test_item.storage_location_id,
            name='Retention Blocker Take',
        )
        db.add(take)
        await db.flush()
        db.add(
            StockTakeItem(
                stock_take_id=take.id,
                item_id=async_test_item.id,
                item_name=async_test_item.name,
            )
        )
        await db.commit()

        report = await run_archive_retention(db, now=now)
        await db.commit()

        assert report.purged == 0
        assert len(report.blocked) == 1
        assert report.blocked[0]['types'] == ['stock_take_items']

        result = await db.execute(select(Item).where(Item.id == async_test_item.id))
        assert result.scalars().first() is not None

    async def test_an_unexpected_purge_failure_is_reported_and_the_run_continues(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user,
        async_test_item: Item,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """One exploding purge → blocked; the other items and orgs still purge."""
        from app.models.storage_location import StorageLocation
        from app.services import audit_service
        from app.services.items._retention import run_archive_retention

        db = real_async_db_session
        now = datetime.now(UTC)
        async_test_household.settings = {'archive_retention_days': 1}
        async_test_item.is_deleted = True
        async_test_item.deleted_at = now - timedelta(days=5)
        async_test_item.deletion_reason = 'OTHER'

        second_org = Organization(
            name='Second Test Organization',
            settings={'archive_retention_days': 1},
        )
        db.add(second_org)
        await db.flush()
        second_shelf = StorageLocation(
            organization_id=second_org.id,
            name='Second Shelf',
            created_by=async_test_user.id,
        )
        db.add(second_shelf)
        await db.flush()

        doomed = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_item.storage_location_id,
            name='Doomed Archived Item',
            quantity=1,
            is_deleted=True,
            deleted_at=now - timedelta(days=5),
            deletion_reason='OTHER',
        )
        second_good = Item(
            organization_id=second_org.id,
            storage_location_id=second_shelf.id,
            name='Second Org Archived Item',
            quantity=1,
            is_deleted=True,
            deleted_at=now - timedelta(days=5),
            deletion_reason='OTHER',
        )
        second_doomed = Item(
            organization_id=second_org.id,
            storage_location_id=second_shelf.id,
            name='Second Doomed Archived Item',
            quantity=1,
            is_deleted=True,
            deleted_at=now - timedelta(days=5),
            deletion_reason='OTHER',
        )
        db.add_all([doomed, second_good, second_doomed])
        await db.commit()

        doomed_ids = {doomed.id, second_doomed.id}
        real_log_purge = audit_service.log_purge_async

        # Explode after the purge already touched the session: with no active
        # transaction a rollback is a no-op, and the bug this pins (expired
        # instances read after the handler's rollback) never fires.
        async def explode_in_audit(*args, **kwargs):
            if kwargs.get('target_id') in doomed_ids:
                raise RuntimeError('purge exploded mid-way')
            return await real_log_purge(*args, **kwargs)

        monkeypatch.setattr(audit_service, 'log_purge_async', explode_in_audit)

        report = await run_archive_retention(db, now=now)
        await db.commit()

        assert report.purged == 2
        assert {b['item_id'] for b in report.blocked} == {
            str(item_id) for item_id in doomed_ids
        }
        assert {b['type'] for b in report.blocked} == {'error'}

        remaining = set((await db.execute(select(Item.id))).scalars().all())
        assert remaining == doomed_ids

    async def test_org_without_retention_is_untouched(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_item: Item,
    ) -> None:
        """retention_days null → nothing is purged."""
        from app.services.items._retention import run_archive_retention

        db = real_async_db_session
        now = datetime.now(UTC)
        async_test_item.is_deleted = True
        async_test_item.deleted_at = now - timedelta(days=30)
        async_test_item.deletion_reason = 'OTHER'
        # Explicitly no retention setting.
        async_test_household.settings = {'allow_permanent_delete': True}
        await db.commit()

        report = await run_archive_retention(db, now=now)
        await db.commit()

        assert report.purged == 0
        result = await db.execute(select(Item).where(Item.id == async_test_item.id))
        assert result.scalars().first() is not None
