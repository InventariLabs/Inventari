"""An empty demo database does not hand the instance to whoever registers first.

The demo reset drops the schema and only then creates the demo account, so a
failed seed leaves the users table empty until the next scheduled run. On an
ordinary install an empty users table is exactly the moment the first account
may register itself; on a demo that same moment let a stranger take the
instance and keep it, because the next reset only updates the demo account.
The reset is the one thing allowed to create the demo's account.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.services.auth_service import AuthService

pytestmark = pytest.mark.integration

_BODY = {
    'email': 'stranger@example.com',
    'full_name': 'Stranger',
    'password': 'Str0ng!passphrase',
}


class _ReachedError(RuntimeError):
    """Raised by the stand-in for the account creation, to prove the gate let the caller through."""


@pytest.fixture
def empty_instance(monkeypatch):
    async def no_users(_db):
        return 0

    async def no_such_email(_db, _email):
        return False

    async def create(_db, _user_in):
        raise _ReachedError

    monkeypatch.setattr(AuthService, 'get_user_count_async', staticmethod(no_users))
    monkeypatch.setattr(AuthService, 'email_exists_async', staticmethod(no_such_email))
    monkeypatch.setattr(AuthService, 'register_user_async', staticmethod(create))


class TestRegisteringOnAnEmptyInstance:
    def test_a_demo_refuses_the_first_account_without_an_invite(
        self, client, monkeypatch, empty_instance
    ):
        monkeypatch.setattr(settings, 'INVENTARI_DEMO', True)

        response = client.post('/api/v1/auth/register', json=_BODY)

        assert response.status_code in (400, 422)

    def test_an_ordinary_install_still_bootstraps_its_first_account(
        self, client, monkeypatch, empty_instance
    ):
        monkeypatch.setattr(settings, 'INVENTARI_DEMO', False)

        with pytest.raises(_ReachedError):
            client.post('/api/v1/auth/register', json=_BODY)


class TestTheStatusTheLoginPageReads:
    @pytest.fixture(autouse=True)
    def _no_users(self, monkeypatch):
        async def no_users(_db):
            return 0

        monkeypatch.setattr(AuthService, 'get_user_count_async', staticmethod(no_users))

    def test_a_demo_does_not_offer_first_account_setup(self, client, monkeypatch):
        monkeypatch.setattr(settings, 'INVENTARI_DEMO', True)

        body = client.get('/api/v1/auth/init-status').json()

        assert body['is_initialized'] is True
        assert body['is_demo'] is True

    def test_an_ordinary_empty_install_offers_it(self, client, monkeypatch):
        monkeypatch.setattr(settings, 'INVENTARI_DEMO', False)

        body = client.get('/api/v1/auth/init-status').json()

        assert body['is_initialized'] is False
