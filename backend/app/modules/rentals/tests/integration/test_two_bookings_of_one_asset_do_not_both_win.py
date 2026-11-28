"""Two requests for one asset and one window: exactly one may win.

The test holds the first booking uncommitted and starts the second while the
first transaction is open. The second blocks on the advisory lock the write
path takes before it reads availability; when the first commits, the second
sees the stored booking and refuses it. Remove the lock and the second request
reads a database that does not contain the first yet, writes its own booking,
and both succeed — the assertion that the task is still blocked is what fails.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.contracts import UserContextDTO
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.modules.rentals import service
from app.modules.rentals.exceptions import RentalConflictError
from app.modules.rentals.schemas import BookingCreate, BookingLineIn

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _async_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


class _Asset:
    def __init__(self) -> None:
        self.org_id: UUID
        self.user_id: UUID
        self.item_id: UUID


@pytest.fixture
async def one_projector(real_async_db_session: AsyncSession) -> _Asset:
    from app.core.testing import ModuleTestHelper

    db = real_async_db_session
    fixture = _Asset()
    org = Organization(
        name=f'Rentals race {datetime.now(UTC).timestamp()}',
        enabled_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'equipment',
            'rentals',
        ],
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db,
        org,
        email=f'rentals-race-{org.id.hex[:8]}@example.com',
        role='admin',
    )
    category = Category(
        name='Projector',
        code=f'PROJECTOR_{org.id.hex[:6]}',
        context_tag='equipment',
        organization_id=org.id,
        field_definitions=[],
    )
    db.add(category)
    await db.flush()
    storage_type = StorageType(
        name='Store',
        type_code=f'STORE_{org.id.hex[:6]}',
        behavior_mode='NONE',
    )
    db.add(storage_type)
    await db.flush()
    location = StorageLocation(
        name='Store room',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
    )
    db.add(location)
    await db.flush()
    item = Item(
        name='Projektor 4K #1',
        organization_id=org.id,
        storage_location_id=location.id,
        category_id=category.id,
        quantity=1,
        meta_data={
            'equipment': {
                'model': 'Projektor 4K',
                'serial_number': 'RACE-1',
                'equipment_status': 'AVAILABLE',
            }
        },
    )
    db.add(item)
    await db.commit()
    fixture.org_id = org.id
    fixture.user_id = user.id
    fixture.item_id = item.id
    return fixture


@pytest.mark.integration
class TestOneWindowAdmitsOneBooking:
    async def test_the_second_request_waits_and_then_refuses(
        self, one_projector: _Asset
    ) -> None:
        starts_at = datetime.now(UTC) + timedelta(days=30)
        ends_at = starts_at + timedelta(days=2)
        payload = BookingCreate(
            borrower_name='Pierwszy',
            starts_at=starts_at,
            ends_at=ends_at,
            lines=[BookingLineIn(item_id=one_projector.item_id)],
        )
        engine = create_async_engine(_async_url(), poolclass=NullPool)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        first = factory()
        second = factory()
        user = UserContextDTO(
            id=one_projector.user_id, organization_id=one_projector.org_id
        )
        try:
            await service.create_booking(first, one_projector.org_id, payload, user)
            task = asyncio.create_task(
                service.create_booking(second, one_projector.org_id, payload, user)
            )
            # The second is inside the lock, not decided yet. Without the lock
            # it would already have written its own booking.
            await asyncio.sleep(0.5)
            assert not task.done(), (
                'the second booking of the same asset and window finished '
                'before the first committed — the check and the write do not '
                'share a lock'
            )
            await first.commit()
            with pytest.raises(RentalConflictError):
                await task
        finally:
            await second.rollback()
            await first.rollback()
            await first.close()
            await second.close()
            await engine.dispose()
