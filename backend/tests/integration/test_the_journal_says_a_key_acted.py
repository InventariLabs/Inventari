"""An entry written by an API key says so, and names the key that wrote it.

The journal credited the key's owner and nothing else: `user_email:
qa-one@example.com`, `meta_data: null` — indistinguishable from the same
person working from the screen. Revoking a key then destroys the only way to
answer what that key did, because the revoked key also leaves the list of
keys. The credential is known when the request is authenticated
(`identity_service` resolves the key, prefix and all), so the entry is the
one place it has to arrive.

Two rules hold it together, and both are tested here: the actor is
request-scoped (a key's name never reaches the next request), and adding it
never costs the caller the `meta_data` it wrote itself.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest

from app.core.audit_actor import audit_actor_scope, current_actor, set_api_key_actor
from app.models.audit_log import AuditAction
from app.services.audit_service import log_action_async
from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration

API_KEYS_URL = '/api/v1/api-keys'


def _auth(user) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def admin(real_async_db_session, async_test_household, async_test_user):
    """The org and its user, committed — the HTTP client uses its own session."""
    await real_async_db_session.commit()
    return async_test_user


@pytest.fixture
async def shelf(real_async_db_session, async_test_household, admin):
    from app.models.storage_location import StorageLocation

    row = StorageLocation(
        organization_id=async_test_household.id,
        created_by=admin.id,
        name='Shelf A',
    )
    real_async_db_session.add(row)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(row)
    return row


@pytest.fixture
async def api_key(real_async_client, admin) -> tuple[str, str]:
    """A key issued the way an administrator issues one: (raw, prefix)."""
    response = await real_async_client.post(
        API_KEYS_URL,
        json={
            'name': 'Home Assistant',
            'permissions': ['items:read', 'items:write'],
        },
        headers=_auth(admin),
    )
    assert response.status_code == 201, response.text
    created = response.json()
    return created['raw_key'], created['key_prefix']


async def _create_item(client, headers, shelf, name: str) -> dict:
    response = await client.post(
        '/api/v1/items',
        json={'name': name, 'quantity': 3, 'location_id': str(shelf.id)},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _entries(client, admin, **params) -> list[dict]:
    response = await client.get(
        '/api/v1/audit-log', headers=_auth(admin), params=params
    )
    assert response.status_code == 200, response.text
    return response.json()['items']


async def _note_actor(client, admin, target_id: UUID) -> dict | None:
    entries = await _entries(client, admin, target_id=str(target_id))
    matching = [e for e in entries if e['action'] == 'CREATE']
    assert matching, 'no CREATE entry for the record in the journal'
    return (matching[0]['meta_data'] or {}).get('actor')


@pytest.mark.asyncio
class TestATraceOfTheKey:
    async def test_an_item_created_with_a_key_names_the_key(
        self, real_async_client, admin, shelf, api_key
    ):
        raw_key, prefix = api_key
        item = await _create_item(
            real_async_client, {'Authorization': f'Bearer {raw_key}'}, shelf, 'Beeswax'
        )

        actor = await _note_actor(real_async_client, admin, UUID(item['id']))
        assert actor == {'type': 'api_key', 'key_prefix': prefix}

    async def test_the_owner_is_still_named_beside_the_key(
        self, real_async_client, admin, shelf, api_key
    ):
        """The key acts for a person, and the journal says both — who the
        account was, and which credential of theirs it was."""
        raw_key, _ = api_key
        item = await _create_item(
            real_async_client, {'Authorization': f'Bearer {raw_key}'}, shelf, 'Beeswax'
        )

        entries = await _entries(real_async_client, admin, target_id=item['id'])
        entry = next(e for e in entries if e['action'] == 'CREATE')
        assert entry['user_email'] == admin.email

    async def test_the_same_account_from_the_screen_leaves_no_key(
        self, real_async_client, admin, shelf, api_key
    ):
        """Two entries, same account, same action, one key between them —
        and only one of them says a machine made it."""
        raw_key, prefix = api_key
        by_key = await _create_item(
            real_async_client, {'Authorization': f'Bearer {raw_key}'}, shelf, 'By key'
        )
        by_hand = await _create_item(real_async_client, _auth(admin), shelf, 'By hand')

        assert await _note_actor(real_async_client, admin, UUID(by_key['id'])) == {
            'type': 'api_key',
            'key_prefix': prefix,
        }
        assert await _note_actor(real_async_client, admin, UUID(by_hand['id'])) is None

    async def test_the_prefix_still_names_a_key_the_list_no_longer_holds(
        self, real_async_client, admin, shelf, api_key
    ):
        """The point of revoking a key is asking afterwards what it did."""
        raw_key, prefix = api_key
        item = await _create_item(
            real_async_client, {'Authorization': f'Bearer {raw_key}'}, shelf, 'Beeswax'
        )
        created = await real_async_client.get(API_KEYS_URL, headers=_auth(admin))
        key_id = next(
            k['id'] for k in created.json()['items'] if k['key_prefix'] == prefix
        )
        revoked = await real_async_client.delete(
            f'{API_KEYS_URL}/{key_id}', headers=_auth(admin)
        )
        assert revoked.status_code == 204

        keys = await real_async_client.get(API_KEYS_URL, headers=_auth(admin))
        assert prefix not in keys.text

        # The revoked key's own trail is gone from the list; the entry it
        # wrote still says which key it was.
        actor = await _note_actor(real_async_client, admin, UUID(item['id']))
        assert actor['key_prefix'] == prefix


@pytest.mark.asyncio
class TestTheKeyActionsAreTheirOwnFilter:
    async def test_asking_for_keys_returns_the_keys_and_nothing_else(
        self, real_async_client, admin, shelf, api_key
    ):
        raw_key, prefix = api_key
        by_key = await _create_item(
            real_async_client, {'Authorization': f'Bearer {raw_key}'}, shelf, 'By key'
        )
        by_hand = await _create_item(real_async_client, _auth(admin), shelf, 'By hand')

        entries = await _entries(real_async_client, admin, actor='api_key', limit=500)
        assert entries, 'the filter found no entry the key wrote'
        assert all(
            (e['meta_data'] or {}).get('actor', {}).get('type') == 'api_key'
            for e in entries
        )
        ids = {e['target_id'] for e in entries}
        assert by_key['id'] in ids
        assert by_hand['id'] not in ids

    async def test_asking_for_people_leaves_the_key_actions_out(
        self, real_async_client, admin, shelf, api_key
    ):
        raw_key, prefix = api_key
        by_key = await _create_item(
            real_async_client, {'Authorization': f'Bearer {raw_key}'}, shelf, 'By key'
        )
        by_hand = await _create_item(real_async_client, _auth(admin), shelf, 'By hand')

        entries = await _entries(real_async_client, admin, actor='human', limit=500)
        ids = {e['target_id'] for e in entries}
        assert by_hand['id'] in ids
        assert by_key['id'] not in ids
        # Issuing the key was an administrator at a screen, not the key.
        assert any(
            e['target_type'] == 'api_key'
            and e['action'] == 'CREATE'
            and e['snapshot']['key_prefix'] == prefix
            for e in entries
        )

    async def test_no_actor_parameter_still_returns_both(
        self, real_async_client, admin, shelf, api_key
    ):
        raw_key, _ = api_key
        by_key = await _create_item(
            real_async_client, {'Authorization': f'Bearer {raw_key}'}, shelf, 'By key'
        )
        by_hand = await _create_item(real_async_client, _auth(admin), shelf, 'By hand')

        ids = {e['target_id'] for e in await _entries(real_async_client, admin)}
        assert {by_key['id'], by_hand['id']} <= ids


@pytest.mark.asyncio
class TestTheKeyIsNotRemembered:
    async def test_the_request_after_a_key_carries_no_key(
        self, real_async_client, admin, shelf, api_key
    ):
        """A key's request, then the same account at the keyboard: the two
        entries must read differently.

        The actor a request left behind is what the second one could inherit,
        and under the middleware stack it is invisible — slowapi's
        ``BaseHTTPMiddleware`` hands every request a task of its own, which
        hides such a value rather than making sure there is none. So the test
        puts one in the context itself, the way a request that cleaned up
        after nothing would, and asks the next request to write past it.
        """
        raw_key, prefix = api_key
        by_key = await _create_item(
            real_async_client, {'Authorization': f'Bearer {raw_key}'}, shelf, 'By key'
        )
        set_api_key_actor(prefix)

        by_hand = await _create_item(real_async_client, _auth(admin), shelf, 'By hand')

        assert await _note_actor(real_async_client, admin, UUID(by_key['id'])) == {
            'type': 'api_key',
            'key_prefix': prefix,
        }
        assert await _note_actor(real_async_client, admin, UUID(by_hand['id'])) is None

    async def test_the_scope_forgets_an_actor_when_the_request_ends(self):
        """The dependency itself: what is set inside must not survive it."""
        async with asynccontextmanager(audit_actor_scope)():
            set_api_key_actor('inv_live_0123456789a')
            assert current_actor() == {
                'type': 'api_key',
                'key_prefix': 'inv_live_0123456789a',
            }

        assert current_actor() is None


@pytest.mark.asyncio
class TestTheEntryKeepsWhatTheCallerWrote:
    async def test_the_actor_joins_the_metadata_instead_of_replacing_it(
        self, real_async_db_session, admin, async_test_household
    ):
        """Callers put their own facts in `meta_data` (a stock take's
        discrepancy code, a batch marker). None of them may be dropped
        because the request happened to be a key's."""
        async with asynccontextmanager(audit_actor_scope)():
            set_api_key_actor('inv_live_0123456789a')
            entry = await log_action_async(
                real_async_db_session,
                organization_id=async_test_household.id,
                user_id=admin.id,
                action=AuditAction.UPDATE,
                target_type='item',
                target_id=uuid4(),
                meta_data={'discrepancy_reason_code': 'LOSS'},
            )
        await real_async_db_session.commit()

        assert entry.meta_data == {
            'discrepancy_reason_code': 'LOSS',
            'actor': {'type': 'api_key', 'key_prefix': 'inv_live_0123456789a'},
        }

    async def test_an_entry_written_without_a_request_carries_no_actor(
        self, real_async_db_session, admin, async_test_household
    ):
        """Schedulers and CLI jobs write to the journal too, and they have no
        credential to name."""
        entry = await log_action_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            user_id=None,
            action=AuditAction.CREATE,
            target_type='item',
            target_id=uuid4(),
            meta_data={'bulk': True},
        )
        await real_async_db_session.commit()

        assert entry.meta_data == {'bulk': True}
