"""A key issued for a print agent reaches the print agent's endpoints only.

The agent runs on a machine next to the printer — often a Raspberry Pi in a
garage — and its key is the credential most likely to leak. An ordinary key
may do what its permissions allow, and most reads ask for no permission at
all, so a permission list alone cannot confine it. The ``printing`` scope is
bound to ``printing:agent``: its key reaches the endpoints that guard that
permission, and every other endpoint refuses it — including those that guard
nothing.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import API_KEY_PERMISSIONS
from app.models.organization import Organization
from app.models.user import User
from app.modules.api_keys.api_key_service import create_api_key_async
from app.modules.printing.schemas import PROTOCOL_VERSION
from app.services.token_service import create_access_token, get_password_hash

_AGENT = {
    'name': 'garage',
    'printer_type': 'brother-p710bt',
    'agent_version': '1.0.0',
    'protocol_version': PROTOCOL_VERSION,
}


@pytest.fixture
async def owner(real_async_db_session: AsyncSession) -> User:
    db = real_async_db_session
    org = Organization(
        name='Scoped Keys',
        enabled_modules=['core', 'items', 'locations', 'printing', 'api_keys'],
    )
    db.add(org)
    await db.flush()
    user = User(
        email=f'scoped-{uuid4().hex[:8]}@example.com',
        hashed_password=get_password_hash('irrelevant'),
        full_name='Key Owner',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _key(db: AsyncSession, owner: User, scope: str | None) -> dict[str, str]:
    assert owner.organization_id is not None
    _, raw = await create_api_key_async(
        db,
        organization_id=owner.organization_id,
        user_id=owner.id,
        name=f'key {scope}',
        permissions=(
            ['printing:agent']
            if scope
            else [p.value for p in API_KEY_PERMISSIONS] + ['printing:agent']
        ),
        scopes=[scope] if scope else [],
    )
    # As the request that issues a key does; the client reads it in its own.
    await db.commit()
    return {'X-API-Key': raw}


def _jwt(owner: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(owner.id)})}'
    }


@pytest.mark.integration
@pytest.mark.asyncio
class TestAPrintingKey:
    async def test_it_registers_and_polls_as_a_print_agent(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        owner: User,
    ) -> None:
        headers = await _key(real_async_db_session, owner, 'printing')

        registered = await real_async_client.post(
            '/api/v1/printing/agent/register', json=_AGENT, headers=headers
        )
        claim = await real_async_client.post(
            f'/api/v1/printing/agent/{registered.json()["id"]}/claim', headers=headers
        )

        assert registered.status_code == status.HTTP_200_OK
        assert claim.status_code == status.HTTP_204_NO_CONTENT

    async def test_it_cannot_create_an_item(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        owner: User,
    ) -> None:
        headers = await _key(real_async_db_session, owner, 'printing')

        response = await real_async_client.post(
            '/api/v1/items', json={'name': 'Smuggled'}, headers=headers
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()['detail']['code'] == 'API_KEY_SCOPE_REFUSED'

    async def test_it_cannot_read_what_an_ordinary_key_can(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        owner: User,
    ) -> None:
        scoped = await _key(real_async_db_session, owner, 'printing')
        ordinary = await _key(real_async_db_session, owner, None)

        as_scoped = await real_async_client.get('/api/v1/items', headers=scoped)
        as_ordinary = await real_async_client.get('/api/v1/items', headers=ordinary)

        assert as_ordinary.status_code == status.HTTP_200_OK
        assert as_scoped.status_code == status.HTTP_403_FORBIDDEN

    async def test_an_ordinary_key_with_the_permission_acts_as_an_agent_too(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        owner: User,
    ) -> None:
        headers = await _key(real_async_db_session, owner, None)

        registered = await real_async_client.post(
            '/api/v1/printing/agent/register', json=_AGENT, headers=headers
        )

        assert registered.status_code == status.HTTP_200_OK

    async def test_a_key_without_the_permission_is_no_agent(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        owner: User,
    ) -> None:
        assert owner.organization_id is not None
        _, raw = await create_api_key_async(
            real_async_db_session,
            organization_id=owner.organization_id,
            user_id=owner.id,
            name='reader',
            permissions=['items:read'],
        )
        await real_async_db_session.commit()

        registered = await real_async_client.post(
            '/api/v1/printing/agent/register', json=_AGENT, headers={'X-API-Key': raw}
        )

        assert registered.status_code == status.HTTP_403_FORBIDDEN

    async def test_it_cannot_queue_or_read_jobs_from_the_app_side(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        owner: User,
    ) -> None:
        headers = await _key(real_async_db_session, owner, 'printing')

        response = await real_async_client.get('/api/v1/printing/jobs', headers=headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.integration
@pytest.mark.asyncio
class TestIssuingAScopedKey:
    async def test_the_screen_is_told_which_scopes_exist_and_what_they_bind(
        self, real_async_client: AsyncClient, owner: User
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/api-keys/capabilities', headers=_jwt(owner)
        )

        assert {
            'name': 'printing',
            'permissions': ['printing:agent'],
        } in response.json()['scopes']

    async def test_a_scoped_key_is_issued_with_its_scopes_permissions(
        self, real_async_client: AsyncClient, owner: User
    ) -> None:
        created = await real_async_client.post(
            '/api/v1/api-keys',
            json={'name': 'garage printer', 'scopes': ['printing']},
            headers=_jwt(owner),
        )
        listed = await real_async_client.get('/api/v1/api-keys', headers=_jwt(owner))

        assert created.status_code == status.HTTP_201_CREATED
        assert created.json()['scopes'] == ['printing']
        assert created.json()['permissions'] == ['printing:agent']
        assert [(k['scopes'], k['permissions']) for k in listed.json()['items']] == [
            (['printing'], ['printing:agent'])
        ]

    async def test_a_scoped_key_cannot_carry_a_permission_outside_its_scopes(
        self, real_async_client: AsyncClient, owner: User
    ) -> None:
        response = await real_async_client.post(
            '/api/v1/api-keys',
            json={
                'name': 'greedy printer',
                'scopes': ['printing'],
                'permissions': ['printing:agent', 'items:read'],
            },
            headers=_jwt(owner),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'items:read' in response.json()['detail']['message']

    async def test_a_scope_nobody_registered_is_refused(
        self, real_async_client: AsyncClient, owner: User
    ) -> None:
        response = await real_async_client.post(
            '/api/v1/api-keys',
            json={'name': 'nowhere', 'scopes': ['teleport']},
            headers=_jwt(owner),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
