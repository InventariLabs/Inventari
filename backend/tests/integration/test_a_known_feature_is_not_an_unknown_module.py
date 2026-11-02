"""A feature the installation always has is not a module it does not have.

``/settings/modules/items`` told an admin "There is no module by that
name": the settings endpoint reads the module registry, the products
domain has no BaseModule behind it, and the 404 of that registry miss
read on the screen as "the module does not exist" — while the
organization's own module list names it. A name the installation knows
without a module behind it (an always-on feature, a frontend-only shell
name, the virtual partners card) answers with an empty schema instead;
a 404 stays reserved for a name this installation genuinely does not
have.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
def admin(db_session: Session, test_household: Organization) -> User:
    user = User(
        email=f'feature_settings_admin_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        organization_id=test_household.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


class TestAKnownFeatureWithoutSettingsIsNotUnknown:
    @pytest.mark.parametrize(
        'feature', ['items', 'locations', 'categories', 'spaces', 'partners']
    )
    def test_a_known_feature_answers_with_an_empty_schema(
        self, client: TestClient, admin: User, feature: str
    ) -> None:
        resp = client.get(f'/api/v1/modules/{feature}/settings', headers=_auth(admin))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body['settings'] == {}
        assert body['settings_schema'] is None

    def test_a_name_the_installation_does_not_have_is_still_not_found(
        self, client: TestClient, admin: User
    ) -> None:
        resp = client.get(
            '/api/v1/modules/no-such-feature/settings', headers=_auth(admin)
        )
        assert resp.status_code == 404, resp.text
