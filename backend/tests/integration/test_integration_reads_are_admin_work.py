"""Every read in both integration modules asks the same authority as the writes.

Both modules had the gate on the mutating endpoints only. Webhooks: five
guarded writes, three unguarded GETs — the endpoint list, one endpoint, and the
delivery archive. API keys: create and revoke asked for `org:settings:write`,
the list asked for `org:read`, which every member has.

The shell refuses these screens to a member, so the hole was never on a screen;
it was on the API, which in these two modules is the entire point of the module.

The table is one test on purpose. Each of these routes was closed one at a time
in the first place, and that is how three of them stayed open.
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.organization import Organization
from app.models.user import User
from app.modules.webhooks.models import WebhookEndpoint
from app.services.token_service import create_access_token, get_password_hash


@pytest.fixture
def integrations_org(db_session: Session) -> Organization:
    org = Organization(
        name='Integrations Org',
        enabled_modules=['core', 'api_keys', 'webhooks'],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def member_headers(
    db_session: Session, integrations_org: Organization
) -> dict[str, str]:
    """An ordinary member: role 'user', so `org:read` and nothing beyond it."""
    user = User(
        email=f'integration_member_{uuid4().hex[:8]}@example.com',
        hashed_password=get_password_hash('memberpass'),
        full_name='Integration Member',
        organization_id=integrations_org.id,
        role='user',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(data={'sub': str(user.id)})
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def endpoint_id(db_session: Session, integrations_org: Organization) -> Iterator[str]:
    ep = WebhookEndpoint(
        organization_id=integrations_org.id,
        name='Somewhere',
        url='https://example.com/hook',
        event_types=['item.created'],
        is_active=True,
    )
    db_session.add(ep)
    db_session.commit()
    db_session.refresh(ep)
    yield str(ep.id)


@pytest.mark.integration
class TestMemberCannotReadIntegrations:
    def test_every_read_answers_403(
        self,
        client: TestClient,
        member_headers: dict[str, str],
        endpoint_id: str,
    ) -> None:
        routes = [
            '/api/v1/webhooks/endpoints',
            f'/api/v1/webhooks/endpoints/{endpoint_id}',
            f'/api/v1/webhooks/endpoints/{endpoint_id}/deliveries',
            '/api/v1/webhooks/events',
            '/api/v1/api-keys',
            '/api/v1/api-keys/capabilities',
        ]
        refused = {
            route: client.get(route, headers=member_headers).status_code
            for route in routes
        }
        assert refused == dict.fromkeys(routes, status.HTTP_403_FORBIDDEN)

    def test_the_target_url_does_not_reach_the_body(
        self,
        client: TestClient,
        member_headers: dict[str, str],
        endpoint_id: str,
    ) -> None:
        """The refusal is the point only if the address is not in it anyway."""
        response = client.get('/api/v1/webhooks/endpoints', headers=member_headers)
        assert 'example.com/hook' not in response.text
