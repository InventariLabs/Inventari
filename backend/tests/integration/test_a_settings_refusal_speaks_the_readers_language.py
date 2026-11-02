"""A refused settings save says why in the reader's language.

Saving a module's settings goes through the schema validator, and the
refusals it raised were English sentences under a ``lang: pl`` stamp. The
same door answers for the AI bindings, which refuse an unknown purpose. The
validator now raises keyed rejections and the 400 envelope translates them.
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

PL = {'Accept-Language': 'pl'}


def _auth(user: User, extra: dict[str, str] | None = None) -> dict[str, str]:
    token = create_access_token(data={'sub': str(user.id)})
    return {'Authorization': f'Bearer {token}', **(extra or {})}


@pytest.fixture
def admin(db_session: Session, test_household: Organization) -> User:
    user = User(
        email=f'settings_lang_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        organization_id=test_household.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


class TestSettingsValidatorRefusals:
    def test_a_value_of_the_wrong_type_refuses_in_polish(
        self, client: TestClient, admin: User
    ) -> None:
        resp = client.put(
            '/api/v1/modules/approvals/settings',
            json={'allow_admin_self_approve': 'yes'},
            headers=_auth(admin, PL),
        )

        assert resp.status_code == 400, resp.text
        detail = resp.json()['detail']
        assert detail['message'] == (
            'Ustawienie „allow_admin_self_approve” musi mieć wartość prawda albo fałsz'
        )
        assert detail['lang'] == 'pl'

    def test_an_unknown_setting_refuses_in_polish(
        self, client: TestClient, admin: User
    ) -> None:
        resp = client.put(
            '/api/v1/modules/approvals/settings',
            json={'no_such_setting': 1},
            headers=_auth(admin, PL),
        )

        assert resp.status_code == 400, resp.text
        detail = resp.json()['detail']
        assert detail['message'] == 'Nieznane ustawienie „no_such_setting”'
        assert detail['lang'] == 'pl'

    def test_the_same_refusal_stays_english_for_an_english_reader(
        self, client: TestClient, admin: User
    ) -> None:
        resp = client.put(
            '/api/v1/modules/approvals/settings',
            json={'no_such_setting': 1},
            headers=_auth(admin),
        )

        assert resp.status_code == 400, resp.text
        detail = resp.json()['detail']
        assert detail['message'] == "Unknown setting 'no_such_setting'"
        assert detail['lang'] == 'en'


class TestAiBindingRefusal:
    def test_an_unknown_purpose_refuses_in_polish(
        self, client: TestClient, admin: User
    ) -> None:
        resp = client.put(
            '/api/v1/ai-connections/bindings',
            json={'purpose_key': 'no.such.purpose', 'connection_id': None},
            headers=_auth(admin, PL),
        )

        assert resp.status_code == 400, resp.text
        detail = resp.json()['detail']
        assert detail['message'] == 'Nieznane przeznaczenie AI „no.such.purpose”'
        assert detail['lang'] == 'pl'
