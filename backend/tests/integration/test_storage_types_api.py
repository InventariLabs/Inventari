"""
Integration tests for storage types API endpoints.
"""

import asyncio
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.organization import Organization
from app.models.storage_type import StorageType
from app.services.token_service import create_access_token


def _auth(user):
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.mark.integration
class TestStorageTypesGet:
    """Tests for getting storage types."""

    def test_get_storage_types_list(
        self, client, auth_headers, test_storage_type, test_storage_type_fridge
    ):
        """Test getting list of storage types."""
        response = client.get('/api/v1/location-types', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()['items']
        assert len(data) >= 2
        type_codes = [st['type_code'] for st in data]
        assert 'FREEZER' in type_codes
        assert 'FRIDGE' in type_codes

    def test_get_storage_type_by_id(self, client, auth_headers, test_storage_type):
        """Test getting storage type by ID."""
        response = client.get(
            f'/api/v1/location-types/{test_storage_type.id}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['id'] == str(test_storage_type.id)
        assert data['type_code'] == 'FREEZER'
        assert data['name'] == 'Freezer'

    def test_get_storage_type_not_found(self, client, auth_headers):
        """Test getting non-existent storage type."""
        fake_id = str(uuid4())
        response = client.get(f'/api/v1/location-types/{fake_id}', headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestStorageTypesCreate:
    """Tests for creating storage types."""

    def test_create_storage_type_success(self, client, auth_headers):
        """Test successful storage type creation.

               The code is one the seed does not bring: an organization owns its
        seeded types since, so re-creating one of them is the duplicate
               case below, not this one.
        """
        response = client.post(
            '/api/v1/location-types',
            headers=auth_headers,
            json={'name': 'Crate', 'type_code': 'CRATE', 'icon': '🏺'},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'Crate'
        assert data['type_code'] == 'CRATE'
        assert data['icon'] == '🏺'

    @pytest.mark.asyncio
    async def test_create_storage_type_duplicate_code(
        self, real_async_client, real_async_db_session, async_test_user
    ):
        """Test that duplicate type code is not allowed."""
        db = real_async_db_session
        st = StorageType(
            name='Original Freezer',
            type_code='FREEZER',
            organization_id=async_test_user.organization_id,
        )
        db.add(st)
        await db.commit()

        response = await real_async_client.post(
            '/api/v1/location-types',
            headers=_auth(async_test_user),
            json={'name': 'Another Freezer', 'type_code': 'FREEZER'},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'exists' in response.json()['detail']['message']

    def test_create_storage_type_case_insensitive(self, client, auth_headers):
        """Test that type code is case insensitive."""
        response = client.post(
            '/api/v1/location-types',
            headers=auth_headers,
            json={'name': 'Test Type', 'type_code': 'test'},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['type_code'] == 'TEST'

    def test_create_storage_type_unauthorized(self, client):
        """Test that unauthenticated user cannot create storage type."""
        response = client.post(
            '/api/v1/location-types', json={'name': 'Test', 'type_code': 'TEST'}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestStorageTypesValidation:
    """Tests for storage type validation."""

    @pytest.mark.asyncio
    async def test_get_storage_types_empty(
        self, real_async_client, real_async_db_session, async_test_user
    ):
        """Test getting storage types when none exist."""
        await (
            real_async_db_session.commit()
        )  # commit async_test_user so API can authenticate
        response = await real_async_client.get(
            '/api/v1/location-types', headers=_auth(async_test_user)
        )

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.json()['items'], list)


@pytest.mark.integration
class TestStorageTypesSecurity:
    """Security tests — IDOR prevention for storage types."""

    @pytest.mark.asyncio
    async def test_cannot_access_other_org_storage_types_via_param(
        self, real_async_client, real_async_db_session, async_test_user
    ):
        """
        IDOR guard: passing a foreign organization_id query param must NOT leak
        data from that organization. The endpoint no longer accepts that parameter
        and always scopes results to the authenticated user's own organization.
        """
        db = real_async_db_session
        other_org = Organization(name='Other Org')
        db.add(other_org)
        await db.flush()

        private_st = StorageType(
            name='Secret Wine Rack',
            type_code='SECRET_WINE',
            organization_id=other_org.id,
        )
        db.add(private_st)
        await db.commit()

        response = await real_async_client.get(
            '/api/v1/location-types',
            params={'organization_id': str(other_org.id)},
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_200_OK
        type_codes = [st['type_code'] for st in response.json()['items']]
        assert 'SECRET_WINE' not in type_codes

    def test_get_storage_types_requires_auth(self, client):
        """Unauthenticated request must be rejected."""
        response = client.get('/api/v1/location-types')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_storage_type_from_other_org_not_accessible_by_id(
        self, real_async_client, real_async_db_session, async_test_user
    ):
        """
        IDOR guard: fetching a storage type by ID that belongs to another
        organization must return 404, not the resource.
        """
        db = real_async_db_session
        other_org = Organization(name='Another Org')
        db.add(other_org)
        await db.flush()

        foreign_st = StorageType(
            name='Foreign Shelf',
            type_code='FOREIGN_SHELF',
            organization_id=other_org.id,
        )
        db.add(foreign_st)
        await db.commit()

        response = await real_async_client.get(
            f'/api/v1/location-types/{foreign_st.id}',
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.fixture
def run_module_hook(db_session, async_engine_fixture):
    """Run a module lifecycle hook the way the enable/disable paths do.

       Storage types a module declares are seeded per organization in
    ``system_on_enable`` since; there is no installation-wide sync left
       to stand in for it. The hooks are async-only, and the API client reads
       through its own async session, so they run on their own loop against the
       same database.
    """

    def _run(coro_factory) -> None:
        async def _do() -> None:
            factory = async_sessionmaker(
                async_engine_fixture, class_=AsyncSession, expire_on_commit=False
            )
            async with factory() as session:
                await coro_factory(session)
                await session.commit()

        db_session.commit()
        asyncio.run(_do())

    return _run


@pytest.fixture
def enable_module_for_org(run_module_hook):
    """Enable *module* for *organization_id* through ``system_on_enable``."""

    def _run(module, organization_id) -> None:
        run_module_hook(
            lambda session: module.system_on_enable(organization_id, session)
        )

    return _run


def _visible_codes(client, auth_headers) -> set[str]:
    response = client.get('/api/v1/location-types', headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    return {st['type_code'] for st in response.json()['items']}


@pytest.mark.integration
class TestStorageTypeVisibility:
    """The visibility rule must survive a new vertical without being edited."""

    def test_profile_seeded_types_are_visible(
        self, client, auth_headers, db_session, test_household
    ):
        """Types a product profile seeds reach the client — its own two, not retired duplicates."""
        from app.seed_profiles.equipment_wms import seed_equipment_storage_types

        seed_equipment_storage_types(db_session, organization_id=test_household.id)

        codes = _visible_codes(client, auth_headers)
        assert {'TOOL_ROOM', 'MAINTENANCE_BAY'} <= codes

    def test_the_profiles_retired_duplicates_leave_the_picker_but_stay_in_the_database(
        self, client, auth_headers, db_session, test_household
    ):
        """Installations seeded before the retirement keep their rows, not the picker entries.

        "IT Rack / Server Room" and "Asset Storage" were the profile's
        near-duplicates of the equipment module's "Server Room" and
        "IT Storage / Warehouse" — the same place twice, choosing its field
        set at random. The profile stopped seeding them; the rows an
        organization already has stay (locations stand on them, and the
        edit sheet still names the type for a location that has it).
        """
        retired = ('IT_RACK', 'ASSET_STORAGE')
        rows = {
            code: StorageType(
                name=code.title(),
                type_code=code,
                is_system=True,
                organization_id=test_household.id,
            )
            for code in retired
        }
        for row in rows.values():
            db_session.add(row)
        db_session.commit()

        assert not set(retired) & _visible_codes(client, auth_headers)

        for code, row in rows.items():
            response = client.get(
                f'/api/v1/location-types/{row.id}', headers=auth_headers
            )
            assert response.status_code == status.HTTP_200_OK
            assert response.json()['type_code'] == code

    def test_module_declared_types_are_visible(
        self, client, auth_headers, test_household, enable_module_for_org
    ):
        """Types a module declares reach the organization that enabled it."""
        from app.core.module_registry import module_registry

        module = module_registry.get('equipment')
        assert module is not None
        enable_module_for_org(module, test_household.id)

        declared = {decl.code for decl in module.metadata.storage_types}
        assert declared, 'the equipment module is expected to declare storage types'
        assert declared <= _visible_codes(client, auth_headers)

    def test_module_types_stay_out_of_organizations_without_the_module(
        self, client, auth_headers, test_household, enable_module_for_org, db_session
    ):
        """Enabling a module for one organization does not show its types to another."""
        from app.core.module_registry import module_registry
        from app.models.organization import Organization

        other = Organization(name='Other Tenant', enabled_modules=['core'])
        db_session.add(other)
        db_session.flush()
        db_session.commit()

        module = module_registry.get('equipment')
        assert module is not None
        enable_module_for_org(module, other.id)

        declared = {decl.code for decl in module.metadata.storage_types}
        assert not declared & _visible_codes(client, auth_headers)

    def test_disabling_a_module_keeps_locations_standing_on_its_types(
        self,
        db_session,
        test_household,
        test_user,
        enable_module_for_org,
        run_module_hook,
    ):
        """A module's types outlive its disable, and so do the locations on them."""
        from sqlalchemy import select

        from app.core.module_registry import module_registry
        from app.models.storage_location import StorageLocation
        from app.models.storage_type import StorageType

        module = module_registry.get('equipment')
        assert module is not None
        enable_module_for_org(module, test_household.id)

        server_room = db_session.scalars(
            select(StorageType).where(
                StorageType.type_code == 'SERVER_ROOM',
                StorageType.organization_id == test_household.id,
            )
        ).first()
        assert server_room is not None
        location = StorageLocation(
            organization_id=test_household.id,
            storage_type_id=server_room.id,
            created_by=test_user.id,
            name='Rack Room',
        )
        db_session.add(location)
        db_session.commit()

        run_module_hook(
            lambda session: module.system_on_disable(test_household.id, session)
        )

        db_session.expire_all()
        still_there = db_session.get(StorageLocation, location.id)
        assert still_there is not None
        assert still_there.storage_type_id == server_room.id

    def test_internal_and_retired_types_are_hidden(
        self, client, auth_headers, db_session, test_household
    ):
        """The virtual-location type and the retired set stay out of the picker."""
        retired = ('WINE_CELLAR', 'DRY_STORAGE', 'TOOLBOX', 'BOOKSHELF')
        for code in retired:
            db_session.add(
                StorageType(
                    name=code.title(),
                    type_code=code,
                    is_system=True,
                    organization_id=test_household.id,
                )
            )
        db_session.commit()

        codes = _visible_codes(client, auth_headers)
        assert 'SYSTEM' not in codes
        assert not codes & set(retired)

    def test_a_disabled_module_takes_its_types_out_of_the_picker(
        self, client, auth_headers, db_session, test_household
    ):
        """The rows stay — locations stand on them — but the picker stops offering them.

        A module's declared types are its vocabulary. An organization that
        turned the module off keeps every row (the disable hook deliberately
        leaves them; see the test above), and the list is the one place that
        has to notice: offering a server room to a kitchen teaches the sheet
        a field set the installation can no longer explain.
        """
        server_room = StorageType(
            name='Server Room',
            type_code='SERVER_ROOM',
            is_system=True,
            organization_id=test_household.id,
        )
        db_session.add(server_room)
        test_household.enabled_modules = [
            m for m in test_household.enabled_modules if m != 'equipment'
        ]
        db_session.commit()

        assert 'SERVER_ROOM' not in _visible_codes(client, auth_headers)

        # Hidden is not deleted: the row is still readable by id, which is
        # how a location standing on it keeps naming its type.
        response = client.get(
            f'/api/v1/location-types/{server_room.id}', headers=auth_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['type_code'] == 'SERVER_ROOM'

    def test_the_same_rows_return_once_the_module_is_back(
        self, client, auth_headers, db_session, test_household
    ):
        """Re-enabling the module puts its vocabulary back in the picker."""
        db_session.add(
            StorageType(
                name='Server Room',
                type_code='SERVER_ROOM',
                is_system=True,
                organization_id=test_household.id,
            )
        )
        db_session.commit()
        # test_household ships with every discovered module enabled.

        assert 'SERVER_ROOM' in _visible_codes(client, auth_headers)
