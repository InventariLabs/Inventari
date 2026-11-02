"""The dashboard's two headline numbers must count the same population.

The widget showed "0 Total Assets" next to "7 Checked Out" — figures that
cannot both be true. `total_assets` came from a page of the organisation's
items, newest first, with equipment filtered out of that page afterwards in
Python; `active_assignments` came from a query that joins assignments to items
and knows nothing about that page. Fill the page with non-equipment items and
the asset count reaches zero while the assignment count keeps counting.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.equipment import dashboard_service
from app.modules.equipment.models import EquipmentAssignment

pytestmark = pytest.mark.integration


@pytest.fixture
async def org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name=f'IUX13 Org {uuid.uuid4().hex[:8]}',
        enabled_modules=['core', 'items', 'equipment'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def user(real_async_db_session: AsyncSession, org: Organization) -> User:
    user = User(
        email=f'iux13-{uuid.uuid4().hex[:8]}@test.example',
        hashed_password='x',
        full_name='IUX13 User',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def location(
    real_async_db_session: AsyncSession, org: Organization, user: User
) -> StorageLocation:
    storage_type = StorageType(
        name='IT Storage', type_code='IT_STORAGE', behavior_mode='NONE'
    )
    real_async_db_session.add(storage_type)
    await real_async_db_session.flush()
    location = StorageLocation(
        name='Server Room',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
    )
    real_async_db_session.add(location)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(location)
    return location


async def _make_category(
    db: AsyncSession, *, name: str, code: str, context_tag: str | None
) -> Category:
    category = Category(
        name=name,
        code=code,
        context_tag=context_tag,
        organization_id=None,
        field_definitions=[],
    )
    db.add(category)
    await db.flush()
    await db.refresh(category)
    return category


@pytest.fixture
async def categories(real_async_db_session: AsyncSession) -> tuple[Category, Category]:
    equipment = await _make_category(
        real_async_db_session, name='Laptop', code='LAPTOP', context_tag='equipment'
    )
    other = await _make_category(
        real_async_db_session, name='Consumables', code='CONSUM', context_tag=None
    )
    return equipment, other


async def test_asset_count_survives_a_crowd_of_non_equipment_items(
    real_async_db_session: AsyncSession,
    org: Organization,
    user: User,
    location: StorageLocation,
    categories: tuple[Category, Category],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    equipment_cat, other_cat = categories

    laptop = Item(
        name='ThinkPad',
        organization_id=org.id,
        storage_location_id=location.id,
        category_id=equipment_cat.id,
        quantity=1,
        meta_data={'equipment': {'equipment_status': 'DEPLOYED'}},
    )
    real_async_db_session.add(laptop)
    await real_async_db_session.flush()

    # Newer than the laptop, so they take the whole first page.
    for i in range(5):
        real_async_db_session.add(
            Item(
                name=f'Box of screws {i}',
                organization_id=org.id,
                storage_location_id=location.id,
                category_id=other_cat.id,
                quantity=1,
            )
        )
    await real_async_db_session.flush()

    real_async_db_session.add(
        EquipmentAssignment(
            organization_id=org.id,
            item_id=laptop.id,
            assigned_to_name='IUX13 User',
            checked_out_at=datetime.now(UTC),
            checked_in_at=None,
            checked_out_by=user.id,
        )
    )
    await real_async_db_session.flush()

    # A page smaller than the crowd — the same shape a real organisation with
    # more items than the aggregation cap has.
    monkeypatch.setattr(dashboard_service, '_MAX_EQUIPMENT_ITEMS', 3)

    dashboard = await dashboard_service.get_dashboard(real_async_db_session, org.id)

    assert dashboard.total_assets == 1
    assert dashboard.active_assignments == 1


async def test_assignments_never_outnumber_assets(
    real_async_db_session: AsyncSession,
    org: Organization,
    user: User,
    location: StorageLocation,
    categories: tuple[Category, Category],
) -> None:
    equipment_cat, _ = categories
    for i in range(3):
        item = Item(
            name=f'Laptop {i}',
            organization_id=org.id,
            storage_location_id=location.id,
            category_id=equipment_cat.id,
            quantity=1,
            meta_data={'equipment': {'equipment_status': 'DEPLOYED'}},
        )
        real_async_db_session.add(item)
        await real_async_db_session.flush()
        real_async_db_session.add(
            EquipmentAssignment(
                organization_id=org.id,
                item_id=item.id,
                assigned_to_name='IUX13 User',
                checked_out_at=datetime.now(UTC),
                checked_in_at=None,
                checked_out_by=user.id,
            )
        )
    await real_async_db_session.flush()

    dashboard = await dashboard_service.get_dashboard(real_async_db_session, org.id)

    assert dashboard.active_assignments <= dashboard.total_assets
    assert dashboard.total_assets == 3


async def test_an_asset_filed_under_no_category_still_counts(
    real_async_db_session: AsyncSession,
    org: Organization,
    location: StorageLocation,
    categories: tuple[Category, Category],
) -> None:
    """The count asks the module, not the category column.

    The equipment form never required a category, so plenty of assets have
    none — and they stood in the asset list while this tile answered zero.
    A reader checking the tile against the list caught the two disagreeing
    about one fleet.
    """
    _, other_cat = categories
    real_async_db_session.add(
        Item(
            name='Rack 42U Open Frame',
            organization_id=org.id,
            storage_location_id=location.id,
            category_id=None,
            module_name='equipment',
            quantity=1,
            meta_data={'equipment': {'equipment_status': 'DEPLOYED'}},
        )
    )
    real_async_db_session.add(
        Item(
            name='Box of screws',
            organization_id=org.id,
            storage_location_id=location.id,
            category_id=other_cat.id,
            quantity=1,
        )
    )
    await real_async_db_session.flush()

    dashboard = await dashboard_service.get_dashboard(real_async_db_session, org.id)

    assert dashboard.total_assets == 1
