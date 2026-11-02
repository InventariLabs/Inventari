"""A key prints labels the way the print agent sends it.

The print agent (``print-agent/agent.py``) is the one client this repository
ships for a key. A key travels in its own ``X-API-Key`` header; the Bearer form
it shared with the session token is honoured for one more minor release and
answers with a ``Deprecation`` header. This pins the door the agent knocks on,
the label export, in each form the agent may send.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import API_KEY_PERMISSIONS
from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.user import User
from app.modules.api_keys.api_key_service import create_api_key_async
from app.services.token_service import get_password_hash

_EXPORT = '/api/v1/labels/pool/export/png'
_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


@pytest.fixture
async def key_and_label(real_async_db_session: AsyncSession) -> str:
    db = real_async_db_session
    org = Organization(
        name='Label Shop',
        enabled_modules=['core', 'items', 'locations', 'printing', 'api_keys'],
    )
    db.add(org)
    await db.flush()
    user = User(
        email=f'printer-{uuid4().hex[:8]}@example.com',
        hashed_password=get_password_hash('irrelevant'),
        full_name='Print Agent Owner',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(
        LabelPool(short_code='AGENT-0001', organization_id=org.id, created_by=user.id)
    )
    _, raw = await create_api_key_async(
        db,
        organization_id=org.id,
        user_id=user.id,
        name='print agent',
        permissions=[p.value for p in API_KEY_PERMISSIONS],
    )
    await db.commit()
    return raw


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheKeyThePrintAgentSends:
    async def test_a_key_in_its_own_header_exports_the_waiting_labels(
        self, real_async_client: AsyncClient, key_and_label: str
    ) -> None:
        response = await real_async_client.get(
            _EXPORT, headers={'X-API-Key': key_and_label}
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.content.startswith(_PNG_MAGIC)
        assert 'deprecation' not in response.headers

    async def test_a_bearer_key_still_exports_and_is_told_it_is_deprecated(
        self, real_async_client: AsyncClient, key_and_label: str
    ) -> None:
        response = await real_async_client.get(
            _EXPORT, headers={'Authorization': f'Bearer {key_and_label}'}
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.content.startswith(_PNG_MAGIC)
        assert response.headers['deprecation'] == '@1792713600'

    async def test_a_refused_bearer_key_is_told_too(
        self, real_async_client: AsyncClient
    ) -> None:
        response = await real_async_client.get(
            _EXPORT, headers={'Authorization': 'Bearer inv_live_nosuchkey0123456789'}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers['deprecation'] == '@1792713600'

    async def test_both_forms_together_are_not_marked(
        self, real_async_client: AsyncClient, key_and_label: str
    ) -> None:
        # What the agent sends while 0.11 servers are still about.
        response = await real_async_client.get(
            _EXPORT,
            headers={
                'X-API-Key': key_and_label,
                'Authorization': f'Bearer {key_and_label}',
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert 'deprecation' not in response.headers

    async def test_a_session_token_is_not_marked(
        self, real_async_client: AsyncClient
    ) -> None:
        response = await real_async_client.get(
            _EXPORT, headers={'Authorization': 'Bearer not-a-key'}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert 'deprecation' not in response.headers
