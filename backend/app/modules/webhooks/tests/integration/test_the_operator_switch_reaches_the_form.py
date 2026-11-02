"""The switch that allows a local target has to allow saving one.

`WEBHOOKS_ALLOW_PRIVATE_NETWORKS` was read at delivery time only. Saving
refused a private address whatever the setting said, so an operator who turned
it on got a delivery path to an endpoint that could not be created — and the
user the module exists for, a self-hosted install pointing a webhook at Home
Assistant on the LAN, stayed shut out with the switch on.
"""

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.organization import Organization
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash

LOCAL_TARGET = 'http://192.168.1.50:8123/api/webhook/inventari'


@pytest.fixture
def admin_headers(db_session: Session) -> dict[str, str]:
    org = Organization(name='Self Hosted', enabled_modules=['core', 'webhooks'])
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    user = User(
        email='selfhost_admin@example.com',
        hashed_password=get_password_hash('adminpass'),
        full_name='Self Hosted Admin',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(data={'sub': str(user.id)})
    return {'Authorization': f'Bearer {token}'}


def _create(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post(
        '/api/v1/webhooks/endpoints',
        json={
            'name': 'Home Assistant',
            'url': LOCAL_TARGET,
            'event_types': ['item.created'],
        },
        headers=headers,
    )
    return int(response.status_code)


@pytest.mark.integration
class TestTheSwitchReachesTheForm:
    def test_off_refuses_the_local_address(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, 'WEBHOOKS_ALLOW_PRIVATE_NETWORKS', False)
        assert _create(client, admin_headers) == (status.HTTP_422_UNPROCESSABLE_CONTENT)

    def test_on_lets_the_endpoint_be_saved(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, 'WEBHOOKS_ALLOW_PRIVATE_NETWORKS', True)
        assert _create(client, admin_headers) == status.HTTP_201_CREATED
