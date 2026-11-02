"""Access control on `/admin/stats/*`.

`admin_service` counts across the whole deployment: every organization, every
user, and the AI cost attached to each. Those numbers are superuser material —
gating them on the `admin` role hands one tenant's admin the names, emails and
spend of every other tenant.
"""

import uuid

import pytest
from fastapi import status

from app.core.testing import ModuleTestHelper
from app.models.ai_usage_log import AIUsageLog
from app.models.organization import Organization
from app.services.token_service import create_access_token

ADMIN_STATS_PATHS = (
    '/api/v1/admin/stats/summary',
    '/api/v1/admin/stats/ai-usage',
    '/api/v1/admin/stats/activity',
)


def _auth(user):
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def superuser(real_async_db_session, async_test_household):
    user = await ModuleTestHelper.create_user_async(
        real_async_db_session,
        async_test_household,
        email=f'super_{uuid.uuid4().hex[:8]}@example.com',
    )
    user.is_superuser = True
    await real_async_db_session.flush()
    await real_async_db_session.commit()
    return user


@pytest.fixture
async def second_org_with_ai_usage(real_async_db_session, async_test_user):
    """A second tenant burning AI credits — the data must not leak."""
    other_org = Organization(name=f'Other Org {uuid.uuid4().hex[:6]}')
    real_async_db_session.add(other_org)
    await real_async_db_session.flush()

    other_user = await ModuleTestHelper.create_user_async(
        real_async_db_session,
        other_org,
        email=f'other_{uuid.uuid4().hex[:8]}@example.com',
    )
    for org, user in ((other_org, other_user), (None, async_test_user)):
        real_async_db_session.add(
            AIUsageLog(
                user_id=user.id,
                organization_id=org.id if org else user.organization_id,
                model_name='model-a',
                provider='test-provider',
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                estimated_cost_usd=0.01,
                action_type='chat',
            )
        )
    await real_async_db_session.commit()
    return other_org


@pytest.mark.integration
@pytest.mark.asyncio
class TestAdminStatsRequireSuperuser:
    @pytest.mark.parametrize('path', ADMIN_STATS_PATHS)
    async def test_org_admin_is_rejected(
        self, path, real_async_client, real_async_db_session, async_test_user
    ):
        await real_async_db_session.commit()
        assert async_test_user.role == 'admin'
        assert not async_test_user.is_superuser

        response = await real_async_client.get(path, headers=_auth(async_test_user))

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.text

    @pytest.mark.parametrize('path', ADMIN_STATS_PATHS)
    async def test_superuser_is_allowed(self, path, real_async_client, superuser):
        response = await real_async_client.get(path, headers=_auth(superuser))

        assert response.status_code == status.HTTP_200_OK, response.text

    async def test_ai_usage_spans_every_organization(
        self, real_async_client, superuser, second_org_with_ai_usage
    ):
        response = await real_async_client.get(
            '/api/v1/admin/stats/ai-usage', headers=_auth(superuser)
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        organizations = {row['name'] for row in response.json()['by_organization']}
        assert len(organizations) > 1, (
            'the endpoint reports cross-tenant spend — exactly why it is superuser-only'
        )
