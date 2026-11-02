"""Two people counting the same shelf is two sets of corrections for one truth.

Creating a count by hand takes an advisory lock on the location's whole
family and refuses when a count is already running anywhere in that tree.
The scheduler's path did neither: it read the schedule, resolved the
location and created the count, so a nightly cycle count could start on a
shelf somebody was already counting -- and both passes would post
adjustments against the same stock.

The rule belongs to the location, not to the door it is reached through, so
both paths now go through the same lock and the same question.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.modules.stock_takes.cycle_count_service import (
    create_schedule,
    generate_cycle_count,
)
from app.modules.stock_takes.models import CycleCountScope
from app.modules.stock_takes.stock_take_service import create_stock_take_from_storage

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _Shelf:
    def __init__(self) -> None:
        self.org_id: UUID
        self.user_id: UUID
        self.location_id: UUID
        self.schedule_id: UUID


@pytest.fixture
async def shelf(real_async_db_session: AsyncSession) -> _Shelf:
    """A shelf with something on it, and a schedule aimed at it."""
    import uuid

    from app.core.testing import ModuleTestHelper

    db = real_async_db_session
    fixture = _Shelf()

    org = Organization(
        name=f'Counting {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'stock_takes'],
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'counter_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid.uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    location = StorageLocation(
        name='Aisle 1',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
    )
    db.add(location)
    await db.flush()
    db.add(
        Item(
            name='Rye flour',
            organization_id=org.id,
            storage_location_id=location.id,
            quantity=Decimal('12'),
        )
    )
    await db.commit()

    fixture.org_id = org.id
    fixture.user_id = user.id
    fixture.location_id = location.id

    schedule = await create_schedule(
        db,
        org.id,
        user.id,
        name='Nightly',
        scope=CycleCountScope.ALL,
        scope_filter={'storage_location_id': str(location.id)},
    )
    fixture.schedule_id = schedule.id
    return fixture


class TestTheSchedulerFindsTheShelfBusy:
    async def test_a_cycle_count_is_refused_while_a_count_is_running(
        self, real_async_db_session: AsyncSession, shelf: _Shelf
    ) -> None:
        db = real_async_db_session
        await create_stock_take_from_storage(
            db,
            shelf.org_id,
            shelf.user_id,
            shelf.location_id,
            name='Monday count',
            description=None,
            notes=None,
        )

        with pytest.raises(ValueError):
            await generate_cycle_count(
                db, shelf.schedule_id, shelf.org_id, shelf.user_id
            )

    async def test_a_free_shelf_is_still_counted(
        self, real_async_db_session: AsyncSession, shelf: _Shelf
    ) -> None:
        """The control: the guard must not stop the scheduler doing its job."""
        stock_take = await generate_cycle_count(
            real_async_db_session, shelf.schedule_id, shelf.org_id, shelf.user_id
        )
        assert stock_take.storage_location_id == shelf.location_id


class TestSomebodyFindsTheShelfBusyWithACycleCount:
    async def test_a_manual_count_is_refused_while_a_cycle_count_is_running(
        self, real_async_db_session: AsyncSession, shelf: _Shelf
    ) -> None:
        """Symmetry: the rule belongs to the shelf, not to who asked."""
        db = real_async_db_session
        await generate_cycle_count(db, shelf.schedule_id, shelf.org_id, shelf.user_id)

        with pytest.raises(ValueError):
            await create_stock_take_from_storage(
                db,
                shelf.org_id,
                shelf.user_id,
                shelf.location_id,
                name='Monday count',
                description=None,
                notes=None,
            )
