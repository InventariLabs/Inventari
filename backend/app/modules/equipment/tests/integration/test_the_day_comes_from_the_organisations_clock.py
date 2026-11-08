"""Warranty alerts and book value are dated on the organization's day.

An earlier pass moved the core read-models onto the organization's clock
and left three module paths on the server's ``date.today()``. An organization a day
ahead of the server was told a warranty expiring on its own today expired
yesterday, and the depreciation card was struck as at a day nobody named.

Both tests pick a real zone where the local day differs from the server's
*right now*, so they discriminate at any hour of the day rather than only
around midnight.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.equipment import dashboard_service, depreciation_service
from tests.integration._far_clock import zone_where_today_differs

pytestmark = pytest.mark.integration


@pytest.fixture
async def far_org(real_async_db_session: AsyncSession) -> Organization:
    zone, _ = zone_where_today_differs()
    org = Organization(
        name=f'Far Org {uuid.uuid4().hex[:8]}',
        enabled_modules=['core', 'items', 'equipment'],
        timezone=zone,
    )
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def far_user(real_async_db_session: AsyncSession, far_org: Organization) -> User:
    user = User(
        email=f'far-{uuid.uuid4().hex[:8]}@test.example',
        hashed_password='x',
        full_name='Far User',
        organization_id=far_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def far_location(
    real_async_db_session: AsyncSession, far_org: Organization, far_user: User
) -> StorageLocation:
    storage_type = StorageType(
        name=f'IT {uuid.uuid4().hex[:8]}',
        type_code=f'IT_{uuid.uuid4().hex[:8].upper()}',
        behavior_mode='NONE',
    )
    real_async_db_session.add(storage_type)
    await real_async_db_session.flush()
    location = StorageLocation(
        name='Server Room',
        organization_id=far_org.id,
        storage_type_id=storage_type.id,
        created_by=far_user.id,
    )
    real_async_db_session.add(location)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(location)
    return location


@pytest.fixture
async def far_category(real_async_db_session: AsyncSession) -> Category:
    category = Category(
        name='Laptop',
        code=f'LAPTOP_{uuid.uuid4().hex[:8].upper()}',
        context_tag='equipment',
        organization_id=None,
        field_definitions=[],
    )
    real_async_db_session.add(category)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(category)
    return category


async def _asset(
    db: AsyncSession,
    org: Organization,
    location: StorageLocation,
    category: Category,
    *,
    equipment_meta: dict[str, str],
    purchase_price: Decimal | None = None,
) -> Item:
    item = Item(
        name=f'ThinkPad {uuid.uuid4().hex[:6]}',
        organization_id=org.id,
        storage_location_id=location.id,
        category_id=category.id,
        quantity=1,
        purchase_price=purchase_price,
        meta_data={'equipment': equipment_meta},
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


@pytest.mark.asyncio
async def test_a_warranty_ending_today_is_read_on_the_organisations_today(
    real_async_db_session: AsyncSession,
    far_org: Organization,
    far_user: User,
    far_location: StorageLocation,
    far_category: Category,
) -> None:
    """A warranty ending on the organization's today has nought days left.

    On the server's clock the same date is either tomorrow (one day left) or
    yesterday (already lapsed, so it moves to the expired list) — the two
    assertions below fail in whichever direction the reverted code errs.
    """
    _, org_today = zone_where_today_differs()
    asset = await _asset(
        real_async_db_session,
        far_org,
        far_location,
        far_category,
        equipment_meta={
            'equipment_status': 'DEPLOYED',
            'warranty_until': org_today.isoformat(),
        },
    )

    alerts = await dashboard_service.get_warranty_alerts(
        real_async_db_session, far_org.id, days=30
    )
    expired = await dashboard_service.get_expired_warranty_alerts(
        real_async_db_session, far_org.id
    )

    alert = next((a for a in alerts if a.item_id == asset.id), None)
    assert alert is not None, 'a warranty ending today is still a live warranty'
    assert alert.days_remaining == 0
    assert all(a.item_id != asset.id for a in expired)


@pytest.mark.asyncio
async def test_book_value_is_struck_as_at_the_organisations_day(
    real_async_db_session: AsyncSession,
    far_org: Organization,
    far_user: User,
    far_location: StorageLocation,
    far_category: Category,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reference date handed to the pure calculation is the org's day.

    Straight-line depreciation moves once a month, so no book value on a
    real calendar can tell one day from the next — the only observable is
    the date the service dates the calculation to. That is what is asserted:
    the organization's day, and provably not the server's.
    """
    _, org_today = zone_where_today_differs()
    asset = await _asset(
        real_async_db_session,
        far_org,
        far_location,
        far_category,
        equipment_meta={
            'equipment_status': 'DEPLOYED',
            'purchase_date': date(org_today.year - 2, 1, 1).isoformat(),
        },
        purchase_price=Decimal('1000.00'),
    )

    seen: dict[str, date] = {}
    real_compute = depreciation_service.compute_book_value

    def _spy(*args: object, **kwargs: object) -> dict[str, object]:
        seen['as_of'] = kwargs['as_of']  # type: ignore[assignment]
        return real_compute(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(depreciation_service, 'compute_book_value', _spy)

    valuation = await depreciation_service.get_asset_valuation_async(
        real_async_db_session, far_org.id, asset.id
    )

    assert valuation is not None
    assert seen['as_of'] == org_today
    assert seen['as_of'] != date.today()


def test_book_value_refuses_to_invent_a_reference_date() -> None:
    """``as_of`` is required, so no caller can silently inherit the server day."""
    with pytest.raises(TypeError):
        depreciation_service.compute_book_value(  # type: ignore[call-arg]
            Decimal('1000.00'), date(2024, 1, 1)
        )
