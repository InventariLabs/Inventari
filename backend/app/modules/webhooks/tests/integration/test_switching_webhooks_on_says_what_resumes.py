"""Before Webhooks is switched back on, the store can ask what will start sending.

Switching it off asks first and says "switching this back on resumes sending to
the same addresses" — to whoever switched it off. Months later someone else
switches it on, in one click, and every saved address starts receiving. The
store asks the module what a switch-on would resume; for Webhooks that is the
number of saved endpoints that are active, because a paused or auto-disabled
one does not send and would only inflate the number.
"""

import uuid

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.modules.webhooks.models import WebhookEndpoint
from app.services.token_service import create_access_token

URL = '/api/v1/modules/{name}/enable-preview'


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


async def _org_with_endpoints(
    db: AsyncSession, *, active: int, paused: int
) -> tuple[Organization, User]:
    """An organization with Webhooks switched OFF and saved endpoints."""
    org = Organization(
        name=f'Resume Org {uuid.uuid4().hex[:8]}', enabled_modules=['core']
    )
    db.add(org)
    await db.flush()
    admin = User(
        email=f'resume_admin_{uuid.uuid4().hex[:8]}@example.com',
        hashed_password='x',
        full_name='Resume Admin',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    db.add(admin)
    for index in range(active + paused):
        db.add(
            WebhookEndpoint(
                organization_id=org.id,
                name=f'Hook {index}',
                url=f'https://example.com/{index}',
                event_types=['item.created'],
                is_active=index < active,
            )
        )
    await db.commit()
    return org, admin


@pytest.mark.integration
@pytest.mark.asyncio
class TestWhatASwitchOnWouldResume:
    async def test_it_counts_the_saved_endpoints_that_would_send(
        self, real_async_client: AsyncClient, real_async_db_session: AsyncSession
    ) -> None:
        _, admin = await _org_with_endpoints(real_async_db_session, active=2, paused=1)

        response = await real_async_client.get(
            URL.format(name='webhooks'), headers=_auth(admin)
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json() == {'resumes': 2}

    async def test_a_module_with_nothing_to_resume_says_zero(
        self, real_async_client: AsyncClient, real_async_db_session: AsyncSession
    ) -> None:
        _, admin = await _org_with_endpoints(real_async_db_session, active=2, paused=0)

        response = await real_async_client.get(
            URL.format(name='warehouse'), headers=_auth(admin)
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json() == {'resumes': 0}

    async def test_an_unknown_module_is_not_found(
        self, real_async_client: AsyncClient, real_async_db_session: AsyncSession
    ) -> None:
        _, admin = await _org_with_endpoints(real_async_db_session, active=0, paused=0)

        response = await real_async_client.get(
            URL.format(name='no_such_module'), headers=_auth(admin)
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_only_an_admin_may_ask(
        self, real_async_client: AsyncClient, real_async_db_session: AsyncSession
    ) -> None:
        org, _ = await _org_with_endpoints(real_async_db_session, active=1, paused=0)
        member = User(
            email=f'resume_member_{uuid.uuid4().hex[:8]}@example.com',
            hashed_password='x',
            full_name='Resume Member',
            organization_id=org.id,
            role='user',
            is_active=True,
        )
        real_async_db_session.add(member)
        await real_async_db_session.commit()

        response = await real_async_client.get(
            URL.format(name='webhooks'), headers=_auth(member)
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
