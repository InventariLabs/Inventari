"""The journal sees what really changes state.

``log_action_async`` was called by item create, update and soft delete — and
by nothing that actually moves stock. A quantity edit, a transfer, a use, a
dispose and a restore wrote nothing anywhere, nor did anything about the
storages and categories the records are filed under, so the one screen that
reconstructs "why does the warehouse look like this" answered with silences.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration


def _auth(user) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


async def _entries(client, user, **params) -> list[dict]:
    response = await client.get('/api/v1/audit-log', headers=_auth(user), params=params)
    assert response.status_code == 200
    return response.json()['items']


@pytest.fixture
async def admin(real_async_db_session, async_test_household, async_test_user):
    """The org and its admin, committed — the HTTP client uses its own session."""
    await real_async_db_session.commit()
    return async_test_user


@pytest.fixture
async def second_location(real_async_db_session, async_test_household, admin):
    from app.models.storage_location import StorageLocation

    loc = StorageLocation(
        organization_id=async_test_household.id,
        created_by=admin.id,
        name='Freezer B',
    )
    real_async_db_session.add(loc)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(loc)
    return loc


@pytest.fixture
async def committed_location(real_async_db_session, async_test_storage_location):
    """The shared location fixture, committed — the HTTP client reads
    through its own session, so a flushed row is not enough."""
    await real_async_db_session.commit()
    return async_test_storage_location


@pytest.fixture
async def created_item(
    real_async_client,
    admin,
    async_test_storage_location,
    real_async_db_session,
):
    # The storage fixture only flushes; the HTTP client reads through its
    # own session, so the location has to be committed before the call.
    await real_async_db_session.commit()
    response = await real_async_client.post(
        '/api/v1/items',
        json={
            'name': 'Journal Milk',
            'location_id': str(async_test_storage_location.id),
            'quantity': 4,
        },
        headers=_auth(admin),
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
class TestItemMovementsAreRecorded:
    async def test_a_quantity_change_is_recorded_with_both_values(
        self, real_async_client, admin, created_item
    ):
        changed = await real_async_client.patch(
            f'/api/v1/items/{created_item["id"]}/quantity',
            json={'quantity': 2},
            headers=_auth(admin),
        )
        assert changed.status_code == 200

        entries = await _entries(real_async_client, admin, target_type='item')
        entry = next(e for e in entries if e['action'] == 'QUANTITY_CHANGE')
        # The audit snapshot carries the exact Decimals as strings.
        assert entry['snapshot']['before'] == {'quantity': '4.000'}
        assert entry['snapshot']['after'] == {'quantity': '2.000'}
        assert entry['user_email'] == admin.email

    async def test_an_update_says_which_record_it_is_about(
        self, real_async_client, admin, created_item
    ):
        # Every other entry about this item names it; the UPDATE snapshot
        # carried before/after/fields and no name, so the Target column fell
        # back to eight characters of the id — twice, side by side. The bulk
        # edit next door already wrote the name.
        edited = await real_async_client.put(
            f'/api/v1/items/{created_item["id"]}',
            json={'name': 'Journal Butter'},
            headers=_auth(admin),
        )
        assert edited.status_code == 200

        entries = await _entries(real_async_client, admin, target_type='item')
        entry = next(e for e in entries if e['action'] == 'UPDATE')
        assert entry['snapshot']['name'] == 'Journal Butter'

    async def test_a_move_is_recorded_with_location_names(
        self,
        real_async_client,
        admin,
        created_item,
        async_test_storage_location,
        second_location,
    ):
        moved = await real_async_client.patch(
            f'/api/v1/items/{created_item["id"]}/move',
            json={'to_location_id': str(second_location.id)},
            headers=_auth(admin),
        )
        assert moved.status_code == 200

        entries = await _entries(real_async_client, admin, target_type='item')
        entry = next(e for e in entries if e['action'] == 'MOVE')
        assert entry['snapshot']['before']['location'] == 'Kitchen Freezer'
        assert entry['snapshot']['after']['location'] == 'Freezer B'

    async def test_a_use_is_recorded_with_its_reason(
        self, real_async_client, admin, created_item
    ):
        used = await real_async_client.patch(
            f'/api/v1/items/{created_item["id"]}/consume',
            json={'quantity': 1, 'reason': 'drunk', 'notes': 'breakfast'},
            headers=_auth(admin),
        )
        assert used.status_code == 200

        entries = await _entries(real_async_client, admin, target_type='item')
        entry = next(e for e in entries if e['action'] == 'USE')
        assert entry['snapshot']['before'] == {'quantity': 4.0}
        assert entry['snapshot']['after'] == {'quantity': 3.0}
        assert entry['reason'] == 'drunk'
        assert entry['meta_data'] == {'notes': 'breakfast'}

    async def test_a_dispose_is_recorded_as_its_own_verb(
        self, real_async_client, admin, created_item
    ):
        disposed = await real_async_client.patch(
            f'/api/v1/items/{created_item["id"]}/discard',
            json={'quantity': 1, 'reason': 'expired'},
            headers=_auth(admin),
        )
        assert disposed.status_code == 200

        entries = await _entries(real_async_client, admin, target_type='item')
        entry = next(e for e in entries if e['action'] == 'DISPOSE')
        assert entry['snapshot']['after'] == {'quantity': 3.0}
        assert entry['reason'] == 'expired'

    async def test_a_restore_pairs_the_soft_delete(
        self, real_async_client, admin, created_item
    ):
        deleted = await real_async_client.request(
            'DELETE',
            f'/api/v1/items/{created_item["id"]}',
            json={'reason': 'OTHER'},
            headers=_auth(admin),
        )
        assert deleted.status_code == 204
        restored = await real_async_client.post(
            f'/api/v1/items/{created_item["id"]}/restore',
            headers=_auth(admin),
        )
        assert restored.status_code == 200

        entries = await _entries(real_async_client, admin, target_type='item')
        restore = next(e for e in entries if e['action'] == 'RESTORE')
        assert restore['snapshot']['before']['is_deleted'] is True
        assert restore['snapshot']['after']['is_deleted'] is False
        # The quantity came back from the deletion history, and the journal
        # row says so.
        assert restore['snapshot']['after']['quantity'] == 4.0

    async def test_a_create_carries_what_the_record_came_with(
        self, real_async_client, admin, created_item, async_test_storage_location
    ):
        entries = await _entries(real_async_client, admin, target_type='item')
        entry = next(e for e in entries if e['action'] == 'CREATE')
        assert entry['snapshot']['name'] == 'Journal Milk'
        assert entry['snapshot']['quantity'] == 4.0
        assert entry['snapshot']['storage_location_id'] == str(
            async_test_storage_location.id
        )


@pytest.mark.asyncio
class TestStorageAndCategoryActsAreRecorded:
    async def test_creating_a_location_is_recorded(self, real_async_client, admin):
        response = await real_async_client.post(
            '/api/v1/locations',
            json={'name': f'Journal Shelf {uuid4().hex[:6]}'},
            headers=_auth(admin),
        )
        assert response.status_code == 201

        entries = await _entries(real_async_client, admin, target_type='storage')
        entry = next(e for e in entries if e['action'] == 'CREATE')
        assert entry['snapshot']['name'].startswith('Journal Shelf')

    async def test_a_rename_is_recorded_with_both_values(
        self, real_async_client, admin, committed_location
    ):
        renamed = await real_async_client.put(
            f'/api/v1/locations/{committed_location.id}',
            json={'name': 'Kitchen Freezer Renamed'},
            headers=_auth(admin),
        )
        assert renamed.status_code == 200

        entries = await _entries(real_async_client, admin, target_type='storage')
        entry = next(e for e in entries if e['action'] == 'UPDATE')
        assert entry['snapshot']['before'] == {
            'name': 'Kitchen Freezer',
        }
        assert entry['snapshot']['after'] == {
            'name': 'Kitchen Freezer Renamed',
        }

    async def test_a_usage_change_is_refused_and_recorded_nothing(
        self, real_async_client, admin, committed_location
    ):
        # The user path is gone: a location's usage is immutable and
        # the API answers with a refusal. A refused write changes no state,
        # so the journal stays out of it — the usage diff entry in the
        # service remains only for the system paths that still re-file.
        refused = await real_async_client.put(
            f'/api/v1/locations/{committed_location.id}',
            json={'usage': 'customer'},
            headers=_auth(admin),
        )
        assert refused.status_code == 400

        entries = await _entries(real_async_client, admin, target_type='storage')
        assert all(e['action'] != 'UPDATE' for e in entries)

    async def test_archiving_a_location_is_recorded_as_a_soft_delete(
        self, real_async_client, admin, committed_location
    ):
        response = await real_async_client.post(
            f'/api/v1/locations/{committed_location.id}/archive',
            json={},
            headers=_auth(admin),
        )
        assert response.status_code == 200

        entries = await _entries(real_async_client, admin, target_type='storage')
        entry = next(e for e in entries if e['action'] == 'SOFT_DELETE')
        assert entry['reason'] == 'ARCHIVED'

    async def test_deleting_a_location_is_recorded(
        self, real_async_client, admin, second_location
    ):
        response = await real_async_client.delete(
            f'/api/v1/locations/{second_location.id}',
            headers=_auth(admin),
        )
        assert response.status_code in (200, 204)

        entries = await _entries(real_async_client, admin, target_type='storage')
        entry = next(e for e in entries if e['action'] == 'HARD_DELETE')
        assert entry['snapshot']['name'] == 'Freezer B'

    async def test_a_deleted_category_survives_in_the_entry_that_names_it(
        self, real_async_client, admin
    ):
        # Deleting a category is permanent by design and the dialog says so,
        # which makes the journal the only place its configuration survives.
        # The entry carried the name and nothing else, so whoever deleted a
        # category they had configured rebuilt it from memory.
        created = await real_async_client.post(
            '/api/v1/categories',
            json={
                'name': f'Journal Spices {uuid4().hex[:6]}',
                'icon': 'flame',
                'color': '#ff8800',
                'group_label': 'Pantry',
                'context_tag': 'food',
                'field_definitions': [
                    {'key': 'heat', 'label': 'Heat', 'type': 'number'}
                ],
            },
            headers=_auth(admin),
        )
        assert created.status_code == 201
        category = created.json()

        deleted = await real_async_client.delete(
            f'/api/v1/categories/{category["id"]}',
            headers=_auth(admin),
        )
        assert deleted.status_code == 204

        entries = await _entries(real_async_client, admin, target_type='category')
        entry = next(
            e
            for e in entries
            if e['action'] == 'HARD_DELETE' and e['target_id'] == category['id']
        )
        snapshot = entry['snapshot']
        assert snapshot['name'] == category['name']
        assert snapshot['icon'] == 'flame'
        assert snapshot['color'] == '#ff8800'
        assert snapshot['group_label'] == 'Pantry'
        assert snapshot['context_tag'] == 'food'
        assert snapshot['field_definitions'] == [
            {'key': 'heat', 'label': 'Heat', 'type': 'number'}
        ]

    async def test_category_lifecycle_is_recorded(self, real_async_client, admin):
        created = await real_async_client.post(
            '/api/v1/categories',
            json={'name': f'Journal Cats {uuid4().hex[:6]}'},
            headers=_auth(admin),
        )
        assert created.status_code == 201
        category = created.json()

        renamed = await real_async_client.put(
            f'/api/v1/categories/{category["id"]}',
            json={'name': f'Journal Cats {uuid4().hex[:6]}'},
            headers=_auth(admin),
        )
        assert renamed.status_code == 200

        deleted = await real_async_client.delete(
            f'/api/v1/categories/{category["id"]}',
            headers=_auth(admin),
        )
        assert deleted.status_code == 204

        entries = await _entries(real_async_client, admin, target_type='category')
        actions = [e['action'] for e in entries]
        assert 'CREATE' in actions
        assert 'UPDATE' in actions
        assert 'HARD_DELETE' in actions


@pytest.mark.asyncio
class TestAReorganizationLeavesATrail:
    """The batch door was the one write path that left none.

    A reorganization that moved, created and deleted locations wrote not a
    single journal row, while the same three changes made one at a time were
    fully recorded — the administrator looking for who moved the shelf or
    deleted the zone found silence. The batch rows carry the same shape as
    the single door writes, `parent_name` beside `parent_id` included, and
    `meta_data.bulk` says the rows came as one batch.
    """

    async def _create_location(self, client, admin, name, parent_id=None) -> dict:
        payload = {'name': name}
        if parent_id is not None:
            payload['parent_id'] = parent_id
        response = await client.post(
            '/api/v1/locations', json=payload, headers=_auth(admin)
        )
        assert response.status_code == 201, response.text
        return response.json()

    async def _reorg(self, client, admin, operations):
        return await client.post(
            '/api/v1/locations/reorg',
            json={'operations': operations},
            headers=_auth(admin),
        )

    async def test_moving_and_deleting_locations_writes_entries(
        self, real_async_client, admin
    ):
        source = await self._create_location(real_async_client, admin, 'Journal Source')
        target = await self._create_location(real_async_client, admin, 'Journal Target')
        moved = await self._create_location(
            real_async_client, admin, 'Journal Moved', source['id']
        )
        doomed = await self._create_location(
            real_async_client, admin, 'Journal Doomed', source['id']
        )

        response = await self._reorg(
            real_async_client,
            admin,
            [
                {'op': 'move', 'id': moved['id'], 'parent_id': target['id']},
                {'op': 'delete', 'id': doomed['id']},
            ],
        )
        assert response.status_code == 200, response.text
        assert response.json()['applied'] is True

        entries = await _entries(
            real_async_client, admin, target_type='storage', target_id=moved['id']
        )
        entry = next(e for e in entries if e['action'] == 'UPDATE')
        snapshot = entry['snapshot']
        assert snapshot['name'] == 'Journal Moved'
        # The same shift reaches the journal with the same shape as the edit
        # sheet's move: the parent on both sides, named on both sides.
        assert snapshot['before']['parent_id'] == source['id']
        assert snapshot['before']['parent_name'] == 'Journal Source'
        assert snapshot['after']['parent_id'] == target['id']
        assert snapshot['after']['parent_name'] == 'Journal Target'
        assert entry['meta_data']['bulk'] is True

        entries = await _entries(
            real_async_client, admin, target_type='storage', target_id=doomed['id']
        )
        entry = next(e for e in entries if e['action'] == 'HARD_DELETE')
        snapshot = entry['snapshot']
        assert snapshot['name'] == 'Journal Doomed'
        assert snapshot['parent_id'] == source['id']
        assert snapshot['parent_name'] == 'Journal Source'
        assert snapshot['usage'] == 'internal'
        assert entry['meta_data']['bulk'] is True

    async def test_creating_locations_names_the_parent_each_landed_under(
        self, real_async_client, admin
    ):
        site = await self._create_location(real_async_client, admin, 'Journal Site')

        response = await self._reorg(
            real_async_client,
            admin,
            [
                {
                    'op': 'create',
                    'temporary_id': 'zone',
                    'name': 'Journal Zone',
                    'parent_id': site['id'],
                },
                {
                    'op': 'create',
                    'temporary_id': 'bin',
                    'name': 'Journal Bin',
                    'parent_id': 'zone',
                },
            ],
        )
        assert response.status_code == 200, response.text
        created = response.json()['created']

        entries = await _entries(
            real_async_client, admin, target_type='storage', target_id=created['zone']
        )
        entry = next(e for e in entries if e['action'] == 'CREATE')
        assert entry['snapshot']['name'] == 'Journal Zone'
        assert entry['snapshot']['parent_id'] == site['id']
        assert entry['snapshot']['parent_name'] == 'Journal Site'
        assert entry['snapshot']['usage'] == 'internal'
        assert entry['meta_data']['bulk'] is True

        entries = await _entries(
            real_async_client, admin, target_type='storage', target_id=created['bin']
        )
        entry = next(e for e in entries if e['action'] == 'CREATE')
        # The parent came from the same batch: its name can only come from
        # the plan, not from a row that existed when the batch started.
        assert entry['snapshot']['parent_id'] == created['zone']
        assert entry['snapshot']['parent_name'] == 'Journal Zone'

    async def test_a_refused_batch_writes_no_entries(self, real_async_client, admin):
        """The rows live inside the batch's transaction, so a rejection
        cannot leave a trail of operations that never happened. This passes
        with or without the fix — it pins the atomicity of the entries the
        other tests in this class demand."""
        site = await self._create_location(real_async_client, admin, 'Journal Site')
        await self._create_location(
            real_async_client, admin, 'Journal Zone', site['id']
        )

        response = await self._reorg(
            real_async_client,
            admin,
            [{'op': 'delete', 'id': site['id']}],
        )
        assert response.status_code == 207, response.text
        assert response.json()['applied'] is False

        entries = await _entries(
            real_async_client, admin, target_type='storage', target_id=site['id']
        )
        assert all(e['action'] != 'HARD_DELETE' for e in entries)
