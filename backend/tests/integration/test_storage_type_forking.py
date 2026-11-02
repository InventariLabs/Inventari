from uuid import uuid4

import pytest
from fastapi import status

from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.services.token_service import create_access_token


def _auth(user):
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.mark.integration
@pytest.mark.asyncio
class TestStorageTypeForking:
    """Tests for the Fork-on-Update logic for storage types."""

    async def test_fork_on_update(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """Test that updating a global type creates a organization fork."""
        db = real_async_db_session
        global_type = StorageType(
            name='Global Freezer',
            type_code='G_FREEZER',
            is_system=True,
            organization_id=None,
        )
        db.add(global_type)
        await db.commit()
        global_id = global_type.id

        headers = _auth(async_test_user)
        response = await real_async_client.put(
            f'/api/v1/location-types/{global_id}',
            headers=headers,
            json={'name': 'My Custom Freezer', 'icon': '\U0001f976'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        forked_id = data['id']

        assert forked_id != str(global_id)
        assert data['name'] == 'My Custom Freezer'
        assert data['organization_id'] == str(async_test_household.id)
        assert data['is_system'] is False

        db.expire_all()
        original = await db.get(StorageType, global_id)
        assert original.name == 'Global Freezer'
        assert original.is_system is True

    async def test_fork_updates_locations(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """Test that forking a type updates all relevant storage locations in the organization."""
        db = real_async_db_session
        global_type = StorageType(
            name='Global Fridge',
            type_code='G_FRIDGE',
            is_system=True,
            organization_id=None,
        )
        db.add(global_type)
        await db.flush()

        location = StorageLocation(
            name='My Kitchen Fridge',
            organization_id=async_test_household.id,
            storage_type_id=global_type.id,
            created_by=async_test_user.id,
        )
        db.add(location)
        await db.commit()

        location_id = location.id
        global_id = global_type.id

        headers = _auth(async_test_user)
        response = await real_async_client.put(
            f'/api/v1/location-types/{global_id}',
            headers=headers,
            json={'context_schema': ['brand', 'expiry_date']},
        )
        assert response.status_code == status.HTTP_200_OK
        forked_id = response.json()['id']

        db.expire_all()
        updated_location = await db.get(StorageLocation, location_id)
        assert str(updated_location.storage_type_id) == forked_id
        assert updated_location.storage_type_id != global_id

    async def test_no_fork_for_already_household_type(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """Test that updating an existing organization type does not fork again."""
        db = real_async_db_session
        h_type = StorageType(
            name='Custom Type',
            type_code='CUSTOM',
            organization_id=async_test_household.id,
            is_system=False,
        )
        db.add(h_type)
        await db.commit()
        type_id = h_type.id

        headers = _auth(async_test_user)
        response = await real_async_client.put(
            f'/api/v1/location-types/{type_id}',
            headers=headers,
            json={'name': 'Renamed Custom Type'},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data['id'] == str(type_id)
        assert data['name'] == 'Renamed Custom Type'

    async def test_seeded_type_is_renamed_in_place_but_not_deleted(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """A type a profile seeded for the organization is its own to rename.

        The seeder never rewrites a changed name, so renaming is the supported
        way to adapt a seeded type; only removal is refused, because the next
        profile pick would put the type back.
        """
        db = real_async_db_session
        seeded = StorageType(
            name='Seeded Pantry',
            type_code='SEEDED_PANTRY',
            organization_id=async_test_household.id,
            is_system=True,
        )
        db.add(seeded)
        await db.commit()
        type_id = seeded.id

        headers = _auth(async_test_user)
        response = await real_async_client.put(
            f'/api/v1/location-types/{type_id}',
            headers=headers,
            json={'name': 'Larder'},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['id'] == str(type_id)
        assert data['name'] == 'Larder'
        assert data['is_system'] is True

        response = await real_async_client.delete(
            f'/api/v1/location-types/{type_id}', headers=headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_fork_does_not_affect_other_households(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """Test that forking only updates locations in the current organization."""
        db = real_async_db_session
        global_type = StorageType(
            name='Shared Type', type_code='SHARED', is_system=True, organization_id=None
        )
        db.add(global_type)
        await db.flush()

        loc1 = StorageLocation(
            name='My Loc',
            organization_id=async_test_household.id,
            storage_type_id=global_type.id,
            created_by=async_test_user.id,
        )

        other_household_id = uuid4()
        other_h = Organization(id=other_household_id, name='Other Organization')
        db.add(other_h)
        await db.flush()

        loc2 = StorageLocation(
            name='Other Loc',
            organization_id=other_h.id,
            storage_type_id=global_type.id,
            created_by=async_test_user.id,
        )

        db.add(loc1)
        db.add(loc2)
        await db.commit()

        loc1_id = loc1.id
        loc2_id = loc2.id
        global_id = global_type.id

        headers = _auth(async_test_user)
        await real_async_client.put(
            f'/api/v1/location-types/{global_id}',
            headers=headers,
            json={'name': 'My Version'},
        )

        db.expire_all()
        assert (await db.get(StorageLocation, loc1_id)).storage_type_id != global_id
        assert (await db.get(StorageLocation, loc2_id)).storage_type_id == global_id

    async def test_get_storage_types_lists_in_a_stable_order(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """The listing is a deterministic function of the data, not of the
        table's physical layout.

        With no ORDER BY, Postgres returns rows in heap order — and on a
        table churned by a full parallel run, heap order is not insertion
        order. The same organization could see its types in a different
        order on every read."""
        db = real_async_db_session
        db.add_all(
            [
                StorageType(
                    name='Zulu Room',
                    type_code='ZULU_CODE',
                    organization_id=async_test_household.id,
                ),
                StorageType(
                    name='Alpha Room',
                    type_code='ALPHA_CODE',
                    organization_id=async_test_household.id,
                ),
            ]
        )
        await db.commit()

        headers = _auth(async_test_user)
        response = await real_async_client.get(
            '/api/v1/location-types', headers=headers
        )
        assert response.status_code == 200
        names = [t['name'] for t in response.json()['items']]
        assert names == sorted(names, key=str.casefold)

    async def test_colliding_type_codes_pick_the_first_in_order(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """One row per type_code — and WHICH row survives is decided by the
        deterministic order, never by table layout.

        Two organization rows sharing a code cannot be produced through the
        API (creation refuses a duplicate code), so the collision is planted
        through the session directly: the dedupe behind the endpoint is the
        last line of defense for legacy shapes and must not resolve it by
        accident. Planted in reverse-alphabetical insertion order so the
        passing assertion names 'Abe', not whichever row the heap happened
        to hand back last."""
        db = real_async_db_session
        db.add_all(
            [
                StorageType(
                    name='Abe Freezer',
                    type_code='DUP_CODE',
                    organization_id=async_test_household.id,
                ),
                StorageType(
                    name='Zed Freezer',
                    type_code='DUP_CODE',
                    organization_id=async_test_household.id,
                ),
            ]
        )
        await db.commit()

        headers = _auth(async_test_user)
        response = await real_async_client.get(
            '/api/v1/location-types', headers=headers
        )
        assert response.status_code == 200

        dups = [t for t in response.json()['items'] if t['type_code'] == 'DUP_CODE']
        assert len(dups) == 1
        assert dups[0]['name'] == 'Abe Freezer'

    async def test_get_storage_types_isolation(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """Test that types from other organizations are not returned."""
        db = real_async_db_session
        other_h = Organization(name='Other Organization')
        db.add(other_h)
        await db.flush()

        other_type = StorageType(
            name='Secret Other Type',
            type_code='SECRET',
            is_system=False,
            organization_id=other_h.id,
        )
        db.add(other_type)
        await db.commit()

        headers = _auth(async_test_user)
        response = await real_async_client.get(
            '/api/v1/location-types', headers=headers
        )
        assert response.status_code == 200
        data = response.json()['items']

        secret_types = [t for t in data if t['type_code'] == 'SECRET']
        assert len(secret_types) == 0

        response = await real_async_client.get(
            f'/api/v1/location-types/{other_type.id}', headers=headers
        )
        assert response.status_code == 404
