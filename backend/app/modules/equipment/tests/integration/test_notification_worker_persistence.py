"""Integration test: the equipment notification worker COMMITS its rows.

Regression: run_equipment_notification_check_async previously never
committed — create_async only flushes, the scheduler path never commits,
so every notification was silently rolled back on session close and the
worker produced nothing in production. Found during multi-worker
staging verification.

Also pins the dedup under repeated runs: a second full pass must not
insert a duplicate.
"""

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.equipment.models import EquipmentMaintenanceLog
from app.modules.equipment.notification_worker import (
    run_equipment_notification_check_async,
)
from app.services.auth_service import get_password_hash

TABLES = 'notifications, items, storage_locations, categories, users, organizations'

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def session_factory(
    async_engine_fixture: Any, setup_test_db: Any
) -> SessionFactory:
    factory = async_sessionmaker(
        async_engine_fixture, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        await session.execute(text(f'TRUNCATE {TABLES} RESTART IDENTITY CASCADE'))
        await session.commit()
    return factory


@pytest.fixture
async def org_id(session_factory: SessionFactory) -> uuid.UUID:
    async with session_factory() as db:
        org = Organization(
            name=f'notif-persist-{uuid.uuid4().hex[:6]}',
            enabled_modules=['core', 'items', 'equipment'],
        )
        db.add(org)
        await db.flush()
        admin = User(
            email=f'admin-{uuid.uuid4().hex[:6]}@example.com',
            hashed_password=get_password_hash('x'),
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        db.add(admin)
        await db.flush()  # populate admin.id before it is used as created_by
        cat = Category(name='Laptops', organization_id=org.id, context_tag='equipment')
        db.add(cat)
        loc = StorageLocation(
            name='Site A', organization_id=org.id, created_by=admin.id
        )
        db.add(loc)
        await db.flush()
        db.add(
            Item(
                name='Warranty Laptop',
                organization_id=org.id,
                storage_location_id=loc.id,
                category_id=cat.id,
                meta_data={
                    'equipment': {
                        'warranty_until': str(date.today() + timedelta(days=10))
                    }
                },
            )
        )
        await db.commit()
        return org.id


async def _warranty_notifications(
    session_factory: SessionFactory, org_id: uuid.UUID
) -> int:
    async with session_factory() as db:
        return (
            await db.execute(
                text(
                    'SELECT count(*) FROM notifications n JOIN users u ON u.id = n.user_id '
                    "WHERE u.organization_id = :org AND n.meta_data->>'type' = 'equipment_warranty'"
                ),
                {'org': org_id},
            )
        ).scalar() or 0


@pytest.mark.integration
class TestNotificationWorkerPersistence:
    async def test_notifications_are_committed(
        self, session_factory: SessionFactory, org_id: uuid.UUID
    ) -> None:
        async with session_factory() as db:
            await run_equipment_notification_check_async(db)
        # A NEW session must see the row — proves the worker committed
        # (regression: previously rolled back on session close).
        assert await _warranty_notifications(session_factory, org_id) == 1

    async def test_second_run_does_not_duplicate(
        self, session_factory: SessionFactory, org_id: uuid.UUID
    ) -> None:
        async with session_factory() as db:
            await run_equipment_notification_check_async(db)
        async with session_factory() as db:
            await run_equipment_notification_check_async(db)
        assert await _warranty_notifications(session_factory, org_id) == 1

    async def test_maintenance_reminder_reaches_the_asset_under_no_category(
        self, session_factory: SessionFactory
    ) -> None:
        """The reminder asks the module, not the seeded category codes.

        A rack filed under no category — the equipment form never required
        one — carried a service entry due within the window, and the codes
        the old reader checked had no answer for it: the reminder never
        fired for the very asset a workshop most needs reminding about.
        """
        async with session_factory() as db:
            org = Organization(
                name=f'notif-maint-{uuid.uuid4().hex[:6]}',
                enabled_modules=['core', 'items', 'equipment'],
            )
            db.add(org)
            await db.flush()
            admin = User(
                email=f'admin-{uuid.uuid4().hex[:6]}@example.com',
                hashed_password=get_password_hash('x'),
                organization_id=org.id,
                role='admin',
                is_active=True,
            )
            db.add(admin)
            await db.flush()  # populate admin.id before it is used as created_by
            loc = StorageLocation(
                name='Site B', organization_id=org.id, created_by=admin.id
            )
            db.add(loc)
            await db.flush()
            item = Item(
                name='Rack 42U Open Frame',
                organization_id=org.id,
                storage_location_id=loc.id,
                category_id=None,
                module_name='equipment',
                meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
            )
            db.add(item)
            await db.flush()
            db.add(
                EquipmentMaintenanceLog(
                    organization_id=org.id,
                    item_id=item.id,
                    created_by=admin.id,
                    maintenance_type='PREVENTIVE',
                    title='Quarterly inspection',
                    performed_at=date.today() - timedelta(days=87),
                    next_maintenance_at=date.today() + timedelta(days=3),
                )
            )
            await db.commit()
            org_id = org.id

        async with session_factory() as db:
            await run_equipment_notification_check_async(db)

        async with session_factory() as db:
            count = (
                await db.execute(
                    text(
                        'SELECT count(*) FROM notifications n JOIN users u ON u.id = n.user_id '
                        "WHERE u.organization_id = :org AND n.meta_data->>'type' = 'equipment_maintenance'"
                    ),
                    {'org': org_id},
                )
            ).scalar() or 0
        assert count == 1
