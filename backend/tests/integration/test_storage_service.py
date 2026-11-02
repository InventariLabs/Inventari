"""
Integration tests for StorageService (storage location management).

Tests cover:
- Default site creation and retrieval
- Virtual location management
- Default storage location creation with i18n
- Breadcrumb path generation
- Tree building from flat locations
- Edge cases and error handling

Note: Uses seeded StorageTypes and database fixtures.
"""

import pytest
from sqlalchemy import func, select

from app.core.testing import seed_org_storage_types
from app.i18n.service import set_current_lang
from app.models.organization import Organization
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.storage._defaults import (
    create_default_storage_locations_async,
    ensure_virtual_locations_async,
    get_virtual_location_async,
)
from app.services.storage._queries import get_breadcrumb_async
from app.services.token_service import get_password_hash


@pytest.mark.integration
@pytest.mark.asyncio
class TestStorageService:
    """StorageService integration tests."""

    @pytest.fixture
    async def storage_type(self, real_async_db_session):
        """Get PANTRY storage type from seeded data."""
        st = (
            await real_async_db_session.scalars(
                select(StorageType).where(StorageType.type_code == 'PANTRY')
            )
        ).first()
        if not st:
            pytest.skip('PANTRY StorageType not seeded')
        return st

    @pytest.fixture
    async def system_storage_type(self, real_async_db_session):
        """Get SYSTEM storage type from seeded data."""
        st = (
            await real_async_db_session.scalars(
                select(StorageType).where(StorageType.type_code == 'SYSTEM')
            )
        ).first()
        if not st:
            # Fallback to PANTRY if SYSTEM not seeded
            st = (
                await real_async_db_session.scalars(
                    select(StorageType).where(StorageType.type_code == 'PANTRY')
                )
            ).first()
        return st

    # ======================== get_virtual_location tests ========================

    async def test_get_virtual_location_nonexistent_returns_none(
        self, real_async_db_session, async_test_user
    ):
        """Test getting virtual location that doesn't exist returns None."""
        org = Organization(name='Test Org Virtual Nonexist')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        result = await get_virtual_location_async(
            real_async_db_session, org.id, LocationUsage.CUSTOMER
        )

        assert result is None

    async def test_get_virtual_location_returns_existing(
        self, real_async_db_session, async_test_user
    ):
        """Test retrieving existing virtual location."""
        org = Organization(name='Test Org Virtual Exist')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        await ensure_virtual_locations_async(
            real_async_db_session, org.id, async_test_user.id
        )
        await real_async_db_session.flush()

        result = await get_virtual_location_async(
            real_async_db_session, org.id, LocationUsage.CUSTOMER
        )

        assert result is not None
        assert result.usage == LocationUsage.CUSTOMER
        assert result.organization_id == org.id

    # ======================== ensure_virtual_locations tests ========================

    async def test_ensure_virtual_locations_creates_all_three(
        self, real_async_db_session, async_test_user
    ):
        """Test that all three virtual locations are created."""
        org = Organization(name='Test Org Virtual Create')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        await ensure_virtual_locations_async(
            real_async_db_session, org.id, async_test_user.id
        )
        await real_async_db_session.flush()

        customer = await get_virtual_location_async(
            real_async_db_session, org.id, LocationUsage.CUSTOMER
        )
        inventory = await get_virtual_location_async(
            real_async_db_session, org.id, LocationUsage.INVENTORY
        )
        production = await get_virtual_location_async(
            real_async_db_session, org.id, LocationUsage.PRODUCTION
        )

        assert customer is not None
        assert inventory is not None
        assert production is not None

    async def test_ensure_virtual_locations_idempotent(
        self, real_async_db_session, async_test_user
    ):
        """Test that calling multiple times doesn't create duplicates."""
        org = Organization(name='Test Org Virtual Idempotent')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        await ensure_virtual_locations_async(
            real_async_db_session, org.id, async_test_user.id
        )
        await real_async_db_session.flush()
        count1 = await real_async_db_session.scalar(
            select(func.count(StorageLocation.id)).where(
                StorageLocation.organization_id == org.id,
                StorageLocation.usage.in_(
                    [
                        LocationUsage.CUSTOMER,
                        LocationUsage.INVENTORY,
                        LocationUsage.PRODUCTION,
                    ]
                ),
            )
        )

        await ensure_virtual_locations_async(
            real_async_db_session, org.id, async_test_user.id
        )
        await real_async_db_session.flush()
        count2 = await real_async_db_session.scalar(
            select(func.count(StorageLocation.id)).where(
                StorageLocation.organization_id == org.id,
                StorageLocation.usage.in_(
                    [
                        LocationUsage.CUSTOMER,
                        LocationUsage.INVENTORY,
                        LocationUsage.PRODUCTION,
                    ]
                ),
            )
        )

        assert count1 == count2 == 3

    # ======================== seeded names speak the seed's language ========================

    async def test_virtual_locations_are_seeded_in_the_session_language(
        self, real_async_db_session, async_test_user
    ):
        """The moves register and the valuation print these names; a Polish
        warehouse read 'Consumed (Virtual)' on every row."""
        org = Organization(name='Test Org Virtual PL')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        set_current_lang('pl')
        try:
            await ensure_virtual_locations_async(
                real_async_db_session, org.id, async_test_user.id
            )
            await real_async_db_session.flush()

            customer = await get_virtual_location_async(
                real_async_db_session, org.id, LocationUsage.CUSTOMER
            )
            assert customer.name == 'Zużyte (wirtualna)'
            assert customer.settings['seed']['code'] == 'CONSUMED_VIRTUAL'
        finally:
            set_current_lang('en')

    async def test_untouched_virtual_rows_align_renamed_ones_do_not(
        self, real_async_db_session, async_test_user
    ):
        """Re-seeding in another language moves the rows nobody touched and
        leaves the one a person renamed exactly where they put it."""
        org = Organization(name='Test Org Virtual Align')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )
        user = await self._make_user(real_async_db_session, org, 'align')

        await ensure_virtual_locations_async(real_async_db_session, org.id, user.id)
        await real_async_db_session.flush()

        loss = await get_virtual_location_async(
            real_async_db_session, org.id, LocationUsage.INVENTORY
        )
        loss.name = 'Straty z Recyklingu'
        await real_async_db_session.flush()

        set_current_lang('pl')
        try:
            await ensure_virtual_locations_async(real_async_db_session, org.id, user.id)
            await real_async_db_session.flush()

            consumed = await get_virtual_location_async(
                real_async_db_session, org.id, LocationUsage.CUSTOMER
            )
            assert consumed.name == 'Zużyte (wirtualna)'
            loss_after = await get_virtual_location_async(
                real_async_db_session, org.id, LocationUsage.INVENTORY
            )
            assert loss_after.name == 'Straty z Recyklingu'
        finally:
            set_current_lang('en')

    async def test_profile_locations_seed_in_the_session_language(
        self, real_async_db_session, async_test_user
    ):
        org = Organization(name='Test Org Profile PL', active_profile_id='food_home')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )
        user = await self._make_user(real_async_db_session, org, 'profile-pl')

        set_current_lang('pl')
        try:
            created = await create_default_storage_locations_async(
                real_async_db_session, org.id, user.id
            )
            await real_async_db_session.flush()

            names = {loc.name for loc in created}
            assert names == {'Lodówka', 'Półka A', 'Zamrażalnia'}
        finally:
            set_current_lang('en')

    async def _make_user(self, session, org, prefix: str):
        from app.models.user import User
        from app.services.token_service import get_password_hash

        user = User(
            email=f'{prefix}@example.com',
            hashed_password=get_password_hash('pass123'),
            full_name='Seed Test',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        session.add(user)
        await session.flush()
        return user

    async def test_ensure_virtual_locations_correct_names(
        self, real_async_db_session, async_test_user
    ):
        """Test that virtual locations have correct names."""
        org = Organization(name='Test Org Virtual Names')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        await ensure_virtual_locations_async(
            real_async_db_session, org.id, async_test_user.id
        )
        await real_async_db_session.flush()

        customer = await get_virtual_location_async(
            real_async_db_session, org.id, LocationUsage.CUSTOMER
        )
        inventory = await get_virtual_location_async(
            real_async_db_session, org.id, LocationUsage.INVENTORY
        )
        production = await get_virtual_location_async(
            real_async_db_session, org.id, LocationUsage.PRODUCTION
        )

        assert customer.name == 'Consumed (Virtual)'
        assert inventory.name == 'Inventory Loss (Virtual)'
        assert production.name == 'Production (Virtual)'

    # ======================== create_default_storage_locations tests ========================

    async def test_create_default_storage_locations_food_profile(
        self, real_async_db_session, async_test_user
    ):
        """An organization on the food profile gets that profile's three."""
        org = Organization(name='Test Org for Defaults EN')
        org.active_profile_id = 'food_home'
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        user = User(
            email='defaults-en@example.com',
            hashed_password=get_password_hash('pass123'),
            full_name='Defaults EN Test',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(user)
        await real_async_db_session.flush()

        created = await create_default_storage_locations_async(
            real_async_db_session, org.id, user.id
        )

        assert len(created) == 3

        names = {loc.name for loc in created}
        assert 'Fridge' in names
        assert 'Shelf A' in names
        assert 'Freezer' in names

    async def test_a_location_seeded_under_its_old_english_name_is_not_seeded_twice(
        self, real_async_db_session, async_test_user
    ):
        """The fridge and the freezer were once Cold Storage and Cold Room.

        A row that still bears the old name and carries no seed handle is the
        same location: it joins the new name and no second one appears.
        """
        org = Organization(name='Test Org Old Names')
        org.active_profile_id = 'food_home'
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )
        fridge_type = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'FRIDGE',
                StorageType.organization_id == org.id,
            )
        )
        old = StorageLocation(
            organization_id=org.id,
            storage_type_id=fridge_type.id,
            name='Cold Storage',
            created_by=async_test_user.id,
        )
        real_async_db_session.add(old)
        await real_async_db_session.flush()

        created = await create_default_storage_locations_async(
            real_async_db_session, org.id, async_test_user.id
        )

        assert {loc.name for loc in created} == {'Shelf A', 'Freezer'}
        assert old.name == 'Fridge'

    async def test_create_default_storage_locations_neutral_profile(
        self, real_async_db_session, async_test_user
    ):
        """An organization with no profile is read as neutral, and gets one.

        Measured before: zero. Core asked for FRIDGE, PANTRY and
               FREEZER, the neutral seed brings none of them, and the loop skipped
               all three without a word.
        """
        org = Organization(name='Test Org Neutral Defaults')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        user = User(
            email='neutral-defaults@example.com',
            hashed_password=get_password_hash('pass123'),
            full_name='Neutral Defaults Test',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(user)
        await real_async_db_session.flush()

        created = await create_default_storage_locations_async(
            real_async_db_session, org.id, user.id
        )
        await real_async_db_session.flush()

        assert len(created) == 1
        assert created[0].name == 'Main Storage'
        type_code = await real_async_db_session.run_sync(
            lambda _s: created[0].storage_type.type_code
        )
        assert type_code == 'SHELF'

    async def test_create_default_storage_locations_idempotent(
        self, real_async_db_session, async_test_user
    ):
        """Test that calling twice doesn't create duplicates."""
        org = Organization(name='Test Org for Idempotent')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        user = User(
            email='idempotent@example.com',
            hashed_password=get_password_hash('pass123'),
            full_name='Idempotent Test',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(user)
        await real_async_db_session.flush()

        await create_default_storage_locations_async(
            real_async_db_session, org.id, user.id
        )
        await real_async_db_session.flush()

        count_before = await real_async_db_session.scalar(
            select(func.count(StorageLocation.id)).where(
                StorageLocation.organization_id == org.id,
                StorageLocation.usage == LocationUsage.INTERNAL,
            )
        )

        # Call again
        created = await create_default_storage_locations_async(
            real_async_db_session, org.id, user.id
        )
        await real_async_db_session.flush()

        count_after = await real_async_db_session.scalar(
            select(func.count(StorageLocation.id)).where(
                StorageLocation.organization_id == org.id,
                StorageLocation.usage == LocationUsage.INTERNAL,
            )
        )

        assert len(created) == 0  # Should create nothing
        assert count_before == count_after

    async def test_create_default_storage_locations_creates_and_ensures_virtual(
        self, real_async_db_session, async_test_user
    ):
        """Test that create also ensures virtual locations."""
        org = Organization(name='Test Org for Virtual Ensure')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        user = User(
            email='virtual-ensure@example.com',
            hashed_password=get_password_hash('pass123'),
            full_name='Virtual Ensure Test',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(user)
        await real_async_db_session.flush()

        await create_default_storage_locations_async(
            real_async_db_session, org.id, user.id
        )
        await real_async_db_session.flush()

        virtual = await get_virtual_location_async(
            real_async_db_session, org.id, LocationUsage.CUSTOMER
        )

        assert virtual is not None

    async def test_create_default_storage_locations_correct_storage_types(
        self, real_async_db_session, async_test_user
    ):
        """Test that correct storage types are assigned."""
        org = Organization(name='Test Org for Storage Types')
        org.active_profile_id = 'food_home'
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        user = User(
            email='storage-types@example.com',
            hashed_password=get_password_hash('pass123'),
            full_name='Storage Types Test',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(user)
        await real_async_db_session.flush()

        created = await create_default_storage_locations_async(
            real_async_db_session, org.id, user.id
        )
        await real_async_db_session.flush()

        type_map = await real_async_db_session.run_sync(
            lambda s: {loc.storage_type.type_code: loc for loc in created}
        )

        assert 'FRIDGE' in type_map
        assert 'PANTRY' in type_map
        assert 'FREEZER' in type_map

    async def test_create_default_storage_locations_correct_sites(
        self, real_async_db_session, async_test_user
    ):
        """Test that correct sites are assigned."""
        org = Organization(name='Test Org for Sites')
        org.active_profile_id = 'food_home'
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        user = User(
            email='sites@example.com',
            hashed_password=get_password_hash('pass123'),
            full_name='Sites Test',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(user)
        await real_async_db_session.flush()

        created = await create_default_storage_locations_async(
            real_async_db_session, org.id, user.id
        )

        names = {loc.name for loc in created}

        assert 'Fridge' in names
        assert 'Freezer' in names

    # ======================== get_breadcrumb tests ========================

    async def test_get_breadcrumb_single_location(
        self, real_async_db_session, async_test_user
    ):
        """Test breadcrumb for location without parent."""
        org = Organization(name='Test Org Breadcrumb')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        loc = StorageLocation(
            organization_id=org.id,
            created_by=async_test_user.id,
            usage=LocationUsage.INTERNAL,
            name='A',
        )
        real_async_db_session.add(loc)
        await real_async_db_session.flush()

        result = await get_breadcrumb_async(real_async_db_session, loc.id, org.id)

        assert len(result) == 1
        assert result[0].name == 'A'

    async def test_get_breadcrumb_wrong_org_returns_empty(
        self, real_async_db_session, async_test_user
    ):
        """Test breadcrumb from different org returns empty."""
        org1 = Organization(name='Test Org Breadcrumb Org1')
        org2 = Organization(name='Test Org Breadcrumb Org2')
        real_async_db_session.add_all([org1, org2])
        await real_async_db_session.flush()

        loc = StorageLocation(
            organization_id=org1.id,
            created_by=async_test_user.id,
            usage=LocationUsage.INTERNAL,
            name='A',
        )
        real_async_db_session.add(loc)
        await real_async_db_session.flush()

        result = await get_breadcrumb_async(real_async_db_session, loc.id, org2.id)

        assert result == []

    async def test_get_breadcrumb_nonexistent_location(
        self, real_async_db_session, async_test_user
    ):
        """Test breadcrumb for nonexistent location returns empty."""
        from uuid import uuid4

        org = Organization(name='Test Org Breadcrumb Nonexist')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        result = await get_breadcrumb_async(real_async_db_session, uuid4(), org.id)

        assert result == []


@pytest.mark.integration
@pytest.mark.asyncio
class TestVirtualLocationSeedingIsAudible:
    """A missing SYSTEM type means the seed did not run — it must not pass quietly."""

    async def test_virtual_locations_stand_on_the_system_type(
        self, real_async_db_session, async_test_user
    ):
        """The three virtual locations use SYSTEM, never a stand-in."""
        org = Organization(name='Test Org Virtual System Type')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        system_type = (
            await real_async_db_session.execute(
                select(StorageType).where(
                    StorageType.type_code == 'SYSTEM',
                    StorageType.organization_id == org.id,
                )
            )
        ).scalar_one()

        await ensure_virtual_locations_async(
            real_async_db_session, org.id, async_test_user.id
        )
        await real_async_db_session.flush()

        locations = (
            (
                await real_async_db_session.execute(
                    select(StorageLocation).where(
                        StorageLocation.organization_id == org.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(locations) == 3
        assert {loc.storage_type_id for loc in locations} == {system_type.id}

    async def test_missing_system_type_fails_loudly(
        self, real_async_db_session, async_test_user
    ):
        """Without SYSTEM the call raises instead of substituting or returning."""
        org = Organization(name='Test Org Virtual No System Type')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        system_type = (
            await real_async_db_session.execute(
                select(StorageType).where(
                    StorageType.type_code == 'SYSTEM',
                    StorageType.organization_id == org.id,
                )
            )
        ).scalar_one()
        await real_async_db_session.delete(system_type)
        await real_async_db_session.flush()

        with pytest.raises(RuntimeError, match='SYSTEM'):
            await ensure_virtual_locations_async(
                real_async_db_session, org.id, async_test_user.id
            )

        remaining = (
            await real_async_db_session.execute(
                select(func.count(StorageLocation.id)).where(
                    StorageLocation.organization_id == org.id
                )
            )
        ).scalar()
        assert remaining == 0


@pytest.mark.integration
@pytest.mark.asyncio
class TestDefaultLocationsComeFromTheProfile:
    """The set travels with the profile, and a missing type is audible."""

    async def test_missing_storage_type_is_logged_not_skipped(
        self, real_async_db_session, async_test_user, caplog
    ):
        """A profile asking for a type the organization lacks says so."""
        from sqlalchemy import delete

        org = Organization(name='Test Org Missing Type')
        org.active_profile_id = 'food_home'
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await real_async_db_session.run_sync(
            lambda session: seed_org_storage_types(session, org.id)
        )

        await real_async_db_session.execute(
            delete(StorageType).where(
                StorageType.type_code == 'FREEZER',
                StorageType.organization_id == org.id,
            )
        )
        await real_async_db_session.flush()

        with caplog.at_level('ERROR'):
            created = await create_default_storage_locations_async(
                real_async_db_session, org.id, async_test_user.id
            )

        assert {loc.name for loc in created} == {'Fridge', 'Shelf A'}
        assert 'FREEZER' in caplog.text
        assert 'Freezer' in caplog.text
