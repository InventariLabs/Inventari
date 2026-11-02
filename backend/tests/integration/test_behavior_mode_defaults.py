"""
Lock-before-change tests for behavior_mode on StorageType.

These tests lock the CURRENT behavior so that any accidental regression
during a refactor of the Core is immediately visible.

Current behavior (as of 2026-03-27):
- behavior_mode is stored on StorageType and returned in API responses.
- It does NOT enforce server-side field validation on items.
  Items accept expiry_date/freeze_date regardless of behavior_mode.
- Default behavior_mode on the model is 'STOCK' (neutral; food profile sets EXPIRY explicitly).
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def bm_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='BM Test Org',
        enabled_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'stats',
        ],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def bm_user(real_async_db_session: AsyncSession, bm_org: Organization) -> User:
    user = User(
        email=f'bm_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='BM User',
        organization_id=bm_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def bm_storage_type(real_async_db_session: AsyncSession) -> StorageType:
    st = StorageType(
        name='BM Test Type',
        type_code='BM_TEST_TYPE',
        behavior_mode='NONE',
    )
    real_async_db_session.add(st)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(st)
    return st


@pytest.mark.integration
@pytest.mark.asyncio
class TestBehaviorModeDefaults:
    """Lock current behavior of behavior_mode field on StorageType."""

    async def test_storage_type_default_behavior_mode_is_stock(
        self, real_async_db_session: AsyncSession
    ):
        """Lock: model default for behavior_mode is 'STOCK' (domain-neutral)."""

        def _run(db):
            st = StorageType(name='Test Storage', type_code='TEST_BM_DEFAULT')
            db.add(st)
            db.flush()
            db.refresh(st)
            return st

        st = await real_async_db_session.run_sync(_run)
        assert st.behavior_mode == 'STOCK'

    async def test_storage_type_behavior_mode_expiry_persisted(
        self, real_async_db_session: AsyncSession
    ):
        """Lock: EXPIRY behavior_mode is stored and returned correctly."""

        def _run(db):
            st = StorageType(
                name='Cold Storage A',
                type_code='COLD_A',
                behavior_mode='EXPIRY',
            )
            db.add(st)
            db.flush()
            db.refresh(st)
            return st

        st = await real_async_db_session.run_sync(_run)
        assert st.behavior_mode == 'EXPIRY'

    async def test_storage_type_behavior_mode_freezing_persisted(
        self, real_async_db_session: AsyncSession
    ):
        """Lock: FREEZING behavior_mode is stored and returned correctly."""

        def _run(db):
            st = StorageType(
                name='Cold Storage B',
                type_code='COLD_B',
                behavior_mode='FREEZING',
            )
            db.add(st)
            db.flush()
            db.refresh(st)
            return st

        st = await real_async_db_session.run_sync(_run)
        assert st.behavior_mode == 'FREEZING'

    async def test_storage_type_behavior_mode_stock_persisted(
        self, real_async_db_session: AsyncSession
    ):
        """Lock: STOCK behavior_mode is stored and returned correctly."""

        def _run(db):
            st = StorageType(
                name='Rack A',
                type_code='RACK_A',
                behavior_mode='STOCK',
            )
            db.add(st)
            db.flush()
            db.refresh(st)
            return st

        st = await real_async_db_session.run_sync(_run)
        assert st.behavior_mode == 'STOCK'

    async def test_storage_type_behavior_mode_none_persisted(
        self, real_async_db_session: AsyncSession
    ):
        """Lock: NONE behavior_mode is stored and returned correctly."""

        def _run(db):
            st = StorageType(
                name='System Storage',
                type_code='SYS_BM',
                behavior_mode='NONE',
            )
            db.add(st)
            db.flush()
            db.refresh(st)
            return st

        st = await real_async_db_session.run_sync(_run)
        assert st.behavior_mode == 'NONE'

    async def test_expiry_mode_does_not_block_item_without_expiry_date(
        self, real_async_client, real_async_db_session, bm_org, bm_user, bm_storage_type
    ):
        """Lock: EXPIRY behavior_mode does NOT enforce expiry_date server-side."""
        st = StorageType(
            name='Fridge Lock',
            type_code='FRIDGE_LOCK',
            behavior_mode='EXPIRY',
            is_system=False,
            organization_id=bm_org.id,
        )
        real_async_db_session.add(st)
        await real_async_db_session.flush()

        loc = StorageLocation(
            organization_id=bm_org.id,
            created_by=bm_user.id,
            storage_type_id=st.id,
            name='Lock Test Fridge',
        )
        real_async_db_session.add(loc)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(loc)

        response = await real_async_client.post(
            '/api/v1/items',
            headers=_auth(bm_user),
            json={
                'name': 'Butter',
                'location_id': str(loc.id),
                'quantity': 1,
            },
        )

        assert response.status_code == 201, response.text

    async def test_freezing_mode_does_not_block_item_without_freeze_date(
        self, real_async_client, real_async_db_session, bm_org, bm_user, bm_storage_type
    ):
        """Lock: FREEZING behavior_mode does NOT enforce freeze_date server-side."""
        st = StorageType(
            name='Freezer Lock',
            type_code='FREEZER_LOCK',
            behavior_mode='FREEZING',
            is_system=False,
            organization_id=bm_org.id,
        )
        real_async_db_session.add(st)
        await real_async_db_session.flush()

        loc = StorageLocation(
            organization_id=bm_org.id,
            created_by=bm_user.id,
            storage_type_id=st.id,
            name='Lock Test Freezer',
        )
        real_async_db_session.add(loc)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(loc)

        response = await real_async_client.post(
            '/api/v1/items',
            headers=_auth(bm_user),
            json={
                'name': 'Chicken Fillet',
                'location_id': str(loc.id),
                'quantity': 2,
            },
        )

        assert response.status_code == 201, response.text

    async def test_stock_mode_accepts_item_with_expiry_date(
        self, real_async_client, real_async_db_session, bm_org, bm_user, bm_storage_type
    ):
        """Lock: STOCK behavior_mode does NOT reject extra lifecycle fields."""
        st = StorageType(
            name='Shelf Lock',
            type_code='SHELF_LOCK',
            behavior_mode='STOCK',
            is_system=False,
            organization_id=bm_org.id,
        )
        real_async_db_session.add(st)
        await real_async_db_session.flush()

        loc = StorageLocation(
            organization_id=bm_org.id,
            created_by=bm_user.id,
            storage_type_id=st.id,
            name='Lock Test Shelf',
        )
        real_async_db_session.add(loc)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(loc)

        response = await real_async_client.post(
            '/api/v1/items',
            headers=_auth(bm_user),
            json={
                'name': 'Screw M6',
                'location_id': str(loc.id),
                'quantity': 100,
                'expiry_date': str(date.today() + timedelta(days=365)),
            },
        )

        assert response.status_code == 201, response.text

    async def test_behavior_mode_returned_in_storage_types_list(
        self, real_async_client, real_async_db_session, bm_org, bm_user, bm_storage_type
    ):
        """Lock: behavior_mode is included in GET /location-types response."""
        st = StorageType(
            name='Rack B API',
            type_code='RACK_B_API',
            behavior_mode='STOCK',
            is_system=False,
            organization_id=bm_org.id,
        )
        real_async_db_session.add(st)
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/location-types', headers=_auth(bm_user)
        )

        assert response.status_code == 200
        data = response.json()['items']
        rack = next((s for s in data if s['type_code'] == 'RACK_B_API'), None)
        assert rack is not None
        assert rack['behavior_mode'] == 'STOCK'
