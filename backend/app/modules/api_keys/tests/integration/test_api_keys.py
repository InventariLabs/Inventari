"""Integration tests for the API Keys module.

Tests cover:
- CRUD (create, list, revoke)
- Permission enforcement (ORG_SETTINGS_WRITE for create/revoke, ORG_READ for list)
- API key authentication flow (the key's own header, and the deprecated Bearer form)
- Tenant isolation (org A cannot see/revoke org B keys)
- Key limit enforcement (MAX_KEYS_PER_ORG = 10)
- Expired key rejection
- API keys cannot manage other API keys
- Raw key is returned only once at creation
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash

API_KEYS_URL = '/api/v1/api-keys'


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def org_admin(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='API Keys Org',
        enabled_modules=[],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def admin_user(
    real_async_db_session: AsyncSession, org_admin: Organization
) -> User:
    user = User(
        email='ak_admin@example.com',
        hashed_password=get_password_hash('adminpass'),
        full_name='AK Admin',
        organization_id=org_admin.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def viewer_user(
    real_async_db_session: AsyncSession, org_admin: Organization
) -> User:
    user = User(
        email='ak_viewer@example.com',
        hashed_password=get_password_hash('viewerpass'),
        full_name='AK Viewer',
        organization_id=org_admin.id,
        role='viewer',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def admin_headers(admin_user: User) -> dict[str, str]:
    token = create_access_token(data={'sub': str(admin_user.id)})
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
async def ak_storage_location(
    real_async_db_session: AsyncSession, org_admin: Organization, admin_user: User
) -> StorageLocation:
    storage_type = StorageType(name='AK Warehouse', type_code='AK_WAREHOUSE')
    real_async_db_session.add(storage_type)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(storage_type)

    storage = StorageLocation(
        organization_id=org_admin.id,
        created_by=admin_user.id,
        storage_type_id=storage_type.id,
        name='AK Storage',
    )
    real_async_db_session.add(storage)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(storage)
    return storage


@pytest.fixture
async def viewer_headers(viewer_user: User) -> dict[str, str]:
    token = create_access_token(data={'sub': str(viewer_user.id)})
    return {'Authorization': f'Bearer {token}'}


async def _create_key(
    client: AsyncClient,
    admin_headers: dict[str, str],
    name: str = 'Test Key',
    **overrides: Any,
) -> Response:
    payload = {'name': name, **overrides}
    return await client.post(API_KEYS_URL, json=payload, headers=admin_headers)


# ---------------------------------------------------------------------------
# Tests: POST /api/v1/api-keys  (create)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
class TestCreateApiKey:
    async def test_create_success(
        self, real_async_client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        resp = await _create_key(real_async_client, admin_headers)
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data['name'] == 'Test Key'
        assert data['raw_key'].startswith('inv_live_')
        assert data['key_prefix'] == data['raw_key'][:20]
        assert 'id' in data
        assert data['expires_at'] is None

    async def test_raw_key_returned_only_once(
        self, real_async_client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        resp = await _create_key(real_async_client, admin_headers)
        raw_key = resp.json()['raw_key']

        list_resp = await real_async_client.get(API_KEYS_URL, headers=admin_headers)
        keys = list_resp.json()['items']
        assert len(keys) == 1
        assert 'raw_key' not in keys[0]
        assert keys[0]['key_prefix'] == raw_key[:20]

    async def test_create_with_expiry(
        self, real_async_client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        resp = await _create_key(real_async_client, admin_headers, expires_at=future)
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()['expires_at'] is not None

    async def test_create_empty_name_returns_422(
        self, real_async_client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        resp = await real_async_client.post(
            API_KEYS_URL, json={'name': ''}, headers=admin_headers
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_the_old_single_scope_field_is_refused_not_dropped(
        self, real_async_client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        # A script written for the single ``scope`` string would otherwise get
        # an ordinary key: broader than the printing key it asked for.
        resp = await _create_key(real_async_client, admin_headers, scope='printing')
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert 'scope' in str(resp.json())

        list_resp = await real_async_client.get(API_KEYS_URL, headers=admin_headers)
        assert list_resp.json()['items'] == []

    async def test_viewer_cannot_create(
        self, real_async_client: AsyncClient, viewer_headers: dict[str, str]
    ) -> None:
        resp = await _create_key(real_async_client, viewer_headers, name='Forbidden')
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    async def test_unauthenticated_cannot_create(
        self, real_async_client: AsyncClient
    ) -> None:
        resp = await real_async_client.post(API_KEYS_URL, json={'name': 'Nope'})
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    async def test_key_limit_enforced(
        self, real_async_client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        from app.modules.api_keys.api_key_service import MAX_KEYS_PER_ORG

        for i in range(MAX_KEYS_PER_ORG):
            resp = await _create_key(real_async_client, admin_headers, name=f'Key {i}')
            assert resp.status_code == status.HTTP_201_CREATED

        resp = await _create_key(real_async_client, admin_headers, name='Overflow')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        detail = resp.json()['detail']
        detail_text = detail if isinstance(detail, str) else str(detail)
        assert 'maximum' in detail_text.lower()


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/api-keys  (list)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
class TestListApiKeys:
    async def test_empty_list(
        self, real_async_client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        resp = await real_async_client.get(API_KEYS_URL, headers=admin_headers)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['items'] == []

    async def test_lists_created_keys(
        self, real_async_client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        await _create_key(real_async_client, admin_headers, name='Alpha')
        await _create_key(real_async_client, admin_headers, name='Beta')

        resp = await real_async_client.get(API_KEYS_URL, headers=admin_headers)
        assert resp.status_code == status.HTTP_200_OK
        names = [k['name'] for k in resp.json()['items']]
        assert 'Alpha' in names
        assert 'Beta' in names

    async def test_the_list_is_a_page_with_its_total(
        self, real_async_client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        for name in ('Alpha', 'Beta', 'Gamma'):
            await _create_key(real_async_client, admin_headers, name=name)

        first = await real_async_client.get(
            API_KEYS_URL, headers=admin_headers, params={'limit': 2}
        )
        rest = await real_async_client.get(
            API_KEYS_URL, headers=admin_headers, params={'limit': 2, 'offset': 2}
        )

        assert first.json()['total'] == rest.json()['total'] == 3
        assert (len(first.json()['items']), first.json()['has_more']) == (2, True)
        assert (len(rest.json()['items']), rest.json()['has_more']) == (1, False)
        names = {k['name'] for k in first.json()['items'] + rest.json()['items']}
        assert names == {'Alpha', 'Beta', 'Gamma'}

    async def test_viewer_cannot_list(
        self,
        real_async_client: AsyncClient,
        viewer_headers: dict[str, str],
        admin_headers: dict[str, str],
    ) -> None:
        """Reading the register of issued keys is the authority that issues them.

        This assertion used to say the opposite, and passed: creating and
        revoking asked for `org:settings:write`, listing asked only for
        `org:read`. A viewer could name every key, its prefix, who issued it
        and when it was last used.
        """
        await _create_key(real_async_client, admin_headers, name='Visible')
        resp = await real_async_client.get(API_KEYS_URL, headers=viewer_headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    async def test_includes_created_by_email(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
        admin_user: User,
    ) -> None:
        await _create_key(real_async_client, admin_headers, name='EmailCheck')
        resp = await real_async_client.get(API_KEYS_URL, headers=admin_headers)
        assert resp.json()['items'][0]['created_by_email'] == admin_user.email

    async def test_revoked_keys_hidden_from_list(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
        real_async_db_session: AsyncSession,
    ) -> None:
        create_resp = await _create_key(
            real_async_client, admin_headers, name='ToRevoke'
        )
        key_id = create_resp.json()['id']

        await real_async_client.delete(
            f'{API_KEYS_URL}/{key_id}', headers=admin_headers
        )
        list_resp = await real_async_client.get(API_KEYS_URL, headers=admin_headers)
        assert list_resp.json()['items'] == []


# ---------------------------------------------------------------------------
# Tests: DELETE /api/v1/api-keys/{key_id}  (revoke)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
class TestRevokeApiKey:
    async def test_revoke_success(
        self, real_async_client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        key_id = (await _create_key(real_async_client, admin_headers)).json()['id']

        resp = await real_async_client.delete(
            f'{API_KEYS_URL}/{key_id}', headers=admin_headers
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT

    async def test_revoke_not_found(
        self, real_async_client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        resp = await real_async_client.delete(
            f'{API_KEYS_URL}/{uuid4()}', headers=admin_headers
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    async def test_viewer_cannot_revoke(
        self,
        real_async_client: AsyncClient,
        viewer_headers: dict[str, str],
        admin_headers: dict[str, str],
    ) -> None:
        key_id = (await _create_key(real_async_client, admin_headers)).json()['id']

        resp = await real_async_client.delete(
            f'{API_KEYS_URL}/{key_id}', headers=viewer_headers
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    async def test_revoked_key_cannot_authenticate(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
        real_async_db_session: AsyncSession,
    ) -> None:
        create_resp = await _create_key(real_async_client, admin_headers)
        raw_key = create_resp.json()['raw_key']
        key_id = create_resp.json()['id']

        await real_async_client.delete(
            f'{API_KEYS_URL}/{key_id}', headers=admin_headers
        )

        auth_resp = await real_async_client.get(
            API_KEYS_URL, headers={'X-API-Key': raw_key}
        )
        assert auth_resp.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# Tests: Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
class TestTenantIsolation:
    async def test_org_b_cannot_see_org_a_keys(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
        real_async_db_session: AsyncSession,
    ) -> None:
        await _create_key(real_async_client, admin_headers, name='Org A Key')

        other_org = Organization(name='Other Org', enabled_modules=[])
        real_async_db_session.add(other_org)
        await real_async_db_session.commit()

        other_user = User(
            email='other@example.com',
            hashed_password=get_password_hash('pass'),
            full_name='Other',
            organization_id=other_org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(other_user)
        await real_async_db_session.commit()

        other_token = create_access_token(data={'sub': str(other_user.id)})
        other_headers = {'Authorization': f'Bearer {other_token}'}

        resp = await real_async_client.get(API_KEYS_URL, headers=other_headers)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['items'] == []

    async def test_org_b_cannot_revoke_org_a_key(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
        real_async_db_session: AsyncSession,
    ) -> None:
        key_id = (await _create_key(real_async_client, admin_headers)).json()['id']

        other_org = Organization(name='Other Org 2', enabled_modules=[])
        real_async_db_session.add(other_org)
        await real_async_db_session.commit()

        other_user = User(
            email='other2@example.com',
            hashed_password=get_password_hash('pass'),
            full_name='Other 2',
            organization_id=other_org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(other_user)
        await real_async_db_session.commit()

        other_token = create_access_token(data={'sub': str(other_user.id)})
        other_headers = {'Authorization': f'Bearer {other_token}'}

        resp = await real_async_client.delete(
            f'{API_KEYS_URL}/{key_id}', headers=other_headers
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Tests: API key authentication flow
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
class TestApiKeyAuthentication:
    async def test_api_key_can_authenticate_as_bearer(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
        admin_user: User,
    ) -> None:
        create_resp = await _create_key(real_async_client, admin_headers)
        raw_key = create_resp.json()['raw_key']

        resp = await real_async_client.get(
            API_KEYS_URL, headers={'Authorization': f'Bearer {raw_key}'}
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    async def test_api_key_has_read_access_to_items(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
        admin_user: User,
    ) -> None:
        create_resp = await _create_key(real_async_client, admin_headers)
        raw_key = create_resp.json()['raw_key']
        api_key_headers = {'X-API-Key': raw_key}

        resp = await real_async_client.get('/api/v1/items', headers=api_key_headers)
        assert resp.status_code == status.HTTP_200_OK

    async def test_invalid_key_rejected(self, real_async_client: AsyncClient) -> None:
        resp = await real_async_client.get(
            '/api/v1/items',
            headers={'X-API-Key': 'inv_live_invalidtoken12345'},
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_expired_key_rejected(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
        real_async_db_session: AsyncSession,
    ) -> None:
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        create_resp = await _create_key(
            real_async_client, admin_headers, expires_at=past
        )
        raw_key = create_resp.json()['raw_key']

        resp = await real_async_client.get(
            '/api/v1/items',
            headers={'X-API-Key': raw_key},
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_api_key_cannot_create_other_api_keys(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        create_resp = await _create_key(real_async_client, admin_headers)
        raw_key = create_resp.json()['raw_key']
        api_key_headers = {'X-API-Key': raw_key}

        resp = await real_async_client.post(
            API_KEYS_URL, json={'name': 'Nested'}, headers=api_key_headers
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    async def test_blocked_owner_kills_the_key(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
        admin_user: User,
        real_async_db_session: AsyncSession,
    ) -> None:
        """blocking an account must cut its machine credentials too.

        The JWT path refuses a blocked user; the API-key path only checked
        `is_active`, so an admin blocking a compromised account left every key
        that account owns working until someone revoked them one by one.
        """
        create_resp = await _create_key(real_async_client, admin_headers)
        raw_key = create_resp.json()['raw_key']
        api_key_headers = {'X-API-Key': raw_key}

        assert (
            await real_async_client.get('/api/v1/items', headers=api_key_headers)
        ).status_code == status.HTTP_200_OK

        admin_user.is_blocked = True
        await real_async_db_session.commit()

        key_resp = await real_async_client.get('/api/v1/items', headers=api_key_headers)
        jwt_resp = await real_async_client.get('/api/v1/items', headers=admin_headers)

        assert key_resp.status_code == status.HTTP_403_FORBIDDEN, key_resp.text
        assert jwt_resp.status_code == status.HTTP_403_FORBIDDEN, jwt_resp.text

    async def test_api_key_cannot_revoke_other_api_keys(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        create_resp = await _create_key(real_async_client, admin_headers)
        raw_key = create_resp.json()['raw_key']
        key_id = create_resp.json()['id']
        api_key_headers = {'X-API-Key': raw_key}

        resp = await real_async_client.delete(
            f'{API_KEYS_URL}/{key_id}', headers=api_key_headers
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Tests: Service layer edge cases
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
class TestApiKeyServiceEdgeCases:
    async def test_hash_is_sha256(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
        real_async_db_session: AsyncSession,
    ) -> None:
        import hashlib

        from app.modules.api_keys.models import ApiKey

        create_resp = await _create_key(real_async_client, admin_headers)
        raw_key = create_resp.json()['raw_key']
        key_id = create_resp.json()['id']

        expected_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        def _check_ak(sync_sess: Session) -> None:
            ak = sync_sess.get(ApiKey, key_id)
            assert ak is not None
            assert ak.hashed_key == expected_hash

        await real_async_db_session.run_sync(_check_ak)

    async def test_creation_log_carries_no_part_of_the_key(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        with caplog.at_level(logging.INFO):
            create_resp = await _create_key(real_async_client, admin_headers)
        raw_key = create_resp.json()['raw_key']
        lines = [
            r.getMessage()
            for r in caplog.records
            if 'API key created' in r.getMessage()
        ]

        assert lines
        assert all(raw_key[:12] not in line and 'prefix' not in line for line in lines)

    async def test_key_prefix_is_first_20_chars(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
        real_async_db_session: AsyncSession,
    ) -> None:
        from app.modules.api_keys.models import ApiKey

        create_resp = await _create_key(real_async_client, admin_headers)
        raw_key = create_resp.json()['raw_key']
        key_id = create_resp.json()['id']

        def _check_ak(sync_sess: Session) -> None:
            ak = sync_sess.get(ApiKey, key_id)
            assert ak is not None
            assert ak.key_prefix == raw_key[:20]

        await real_async_db_session.run_sync(_check_ak)

    async def test_revoke_sets_is_active_false(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
        real_async_db_session: AsyncSession,
    ) -> None:
        from app.modules.api_keys.models import ApiKey

        create_resp = await _create_key(real_async_client, admin_headers)
        key_id = create_resp.json()['id']

        await real_async_client.delete(
            f'{API_KEYS_URL}/{key_id}', headers=admin_headers
        )

        def _check_ak(sync_sess: Session) -> None:
            sync_sess.expire_all()
            ak = sync_sess.get(ApiKey, key_id)
            assert ak is not None
            assert ak.is_active is False

        await real_async_db_session.run_sync(_check_ak)


@pytest.mark.integration
@pytest.mark.asyncio
class TestApiKeyPermissions:
    """A key carries its own permission list, chosen from its creator's."""

    async def test_a_key_issued_without_a_choice_gets_the_read_only_default(
        self, real_async_client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        from app.core.contracts import API_KEY_DEFAULT_PERMISSIONS

        created = await _create_key(real_async_client, admin_headers)
        listed = await real_async_client.get(API_KEYS_URL, headers=admin_headers)

        default = sorted(p.value for p in API_KEY_DEFAULT_PERMISSIONS)
        assert all(p.endswith(':read') for p in default)
        assert created.json()['permissions'] == default
        assert listed.json()['items'][0]['permissions'] == default
        assert listed.json()['items'][0]['scopes'] == []

    async def test_capabilities_say_what_the_reader_may_grant(
        self, real_async_client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        from app.core.contracts import API_KEY_DEFAULT_PERMISSIONS, API_KEY_HEADER

        resp = await real_async_client.get(
            f'{API_KEYS_URL}/capabilities', headers=admin_headers
        )
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()

        catalog = {entry['key']: entry for entry in body['catalog']}
        assert catalog['items:delete']['label_key'] == 'permissions:system.items_delete'
        # An admin may grant anything the catalogue holds — except what no
        # key carries: behind `org:settings:write` stand the AI connections,
        # the equipment templates, the SKU schema and the key register.
        assert 'items:delete' in body['grantable']
        assert 'org:settings:write' not in body['grantable']
        assert body['withheld_permissions'] == [
            'admin:access',
            'org:members:write',
            'org:settings:write',
            'system:config:write',
        ]
        assert body['default_permissions'] == sorted(
            p.value for p in API_KEY_DEFAULT_PERMISSIONS
        )
        assert body['admin_areas_blocked'] is True
        assert body['header'] == API_KEY_HEADER == 'X-API-Key'

    async def test_a_key_chosen_to_delete_items_may_delete_them(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
        ak_storage_location: StorageLocation,
    ) -> None:
        resp = await _create_key(
            real_async_client,
            admin_headers,
            permissions=['items:read', 'items:write', 'items:delete'],
        )
        api_key_headers = {'X-API-Key': resp.json()['raw_key']}

        create_resp = await real_async_client.post(
            '/api/v1/items',
            json={
                'name': 'Deleted Via API Key',
                'quantity': 1,
                'location_id': str(ak_storage_location.id),
            },
            headers=api_key_headers,
        )
        delete_resp = await real_async_client.delete(
            f'/api/v1/items/{create_resp.json()["id"]}', headers=api_key_headers
        )

        assert create_resp.status_code == status.HTTP_201_CREATED
        assert delete_resp.status_code == status.HTTP_204_NO_CONTENT

    async def test_a_read_only_key_cannot_write(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
        ak_storage_location: StorageLocation,
    ) -> None:
        resp = await _create_key(
            real_async_client, admin_headers, permissions=['items:read']
        )
        api_key_headers = {'X-API-Key': resp.json()['raw_key']}

        read = await real_async_client.get('/api/v1/items', headers=api_key_headers)
        write = await real_async_client.post(
            '/api/v1/items',
            json={
                'name': 'Refused',
                'quantity': 1,
                'location_id': str(ak_storage_location.id),
            },
            headers=api_key_headers,
        )

        assert read.status_code == status.HTTP_200_OK
        assert write.status_code == status.HTTP_403_FORBIDDEN

    async def test_a_withheld_permission_is_refused_even_to_an_admin(
        self, real_async_client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        resp = await _create_key(
            real_async_client, admin_headers, permissions=['org:settings:write']
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'org:settings:write' in resp.json()['detail']['message']

    async def test_a_permission_the_creator_does_not_hold_is_refused(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org_admin: Organization,
    ) -> None:
        from app.core.testing import ModuleTestHelper
        from app.models.role import Role, UserRole

        manager = await ModuleTestHelper.create_user_async(
            real_async_db_session,
            org_admin,
            email=f'ak-manager-{uuid4().hex[:6]}@example.com',
            role='manager',
        )
        role = Role(
            name='key issuer',
            permissions=['org:settings:write', 'items:read'],
            organization_id=org_admin.id,
        )
        real_async_db_session.add(role)
        await real_async_db_session.flush()
        real_async_db_session.add(UserRole(user_id=manager.id, role_id=role.id))
        await real_async_db_session.commit()
        headers = {
            'Authorization': f'Bearer {create_access_token(data={"sub": str(manager.id)})}'
        }

        held = await _create_key(real_async_client, headers, permissions=['items:read'])
        not_held = await _create_key(
            real_async_client, headers, permissions=['items:write']
        )

        assert held.status_code == status.HTTP_201_CREATED, held.text
        assert not_held.status_code == status.HTTP_400_BAD_REQUEST
        assert 'items:write' in not_held.json()['detail']['message']


@pytest.mark.integration
@pytest.mark.asyncio
class TestApiKeyAuditTrail:
    """Issuing and revoking a key are administrative acts, and left no trace.

       After a session that created two keys, revoked one, enabled three modules
       and changed the organization's settings, the audit log held a single
    entry — the creation of a product. "Who revoked this key" had no
       answer on any screen, least of all the one place a trace belongs.
    """

    async def test_issuing_a_key_is_recorded(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        created = await _create_key(real_async_client, admin_headers, name='CI runner')
        assert created.status_code == status.HTTP_201_CREATED

        log = await real_async_client.get('/api/v1/audit-log', headers=admin_headers)
        (entry,) = [e for e in log.json()['items'] if e['target_type'] == 'api_key']
        assert entry['action'] == 'CREATE'
        assert entry['snapshot']['name'] == 'CI runner'
        assert entry['user_email'] == 'ak_admin@example.com'

    async def test_revoking_a_key_is_recorded_with_its_author(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        created = await _create_key(real_async_client, admin_headers, name='Old script')
        key_id = created.json()['id']

        revoked = await real_async_client.delete(
            f'{API_KEYS_URL}/{key_id}', headers=admin_headers
        )
        assert revoked.status_code == status.HTTP_204_NO_CONTENT

        log = await real_async_client.get('/api/v1/audit-log', headers=admin_headers)
        entries = [
            e
            for e in log.json()['items']
            if e['target_type'] == 'api_key' and e['action'] == 'SOFT_DELETE'
        ]
        assert len(entries) == 1
        assert entries[0]['target_id'] == key_id
        # The row is gone from the list, so the name survives only here.
        assert entries[0]['snapshot']['name'] == 'Old script'
        assert entries[0]['user_email'] == 'ak_admin@example.com'

    async def test_the_raw_key_never_reaches_the_log(
        self,
        real_async_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        created = await _create_key(real_async_client, admin_headers)
        raw_key = created.json()['raw_key']

        log = await real_async_client.get('/api/v1/audit-log', headers=admin_headers)
        assert raw_key not in log.text
