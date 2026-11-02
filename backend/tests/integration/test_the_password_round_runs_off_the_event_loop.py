"""Every door that hashes or checks a password used to run bcrypt on the loop.

bcrypt at cost 12 takes roughly a quarter of a second. Login, registration,
password change and reset each paid it inside the coroutine, so one request
stalled every other request the worker was serving. The tests below put a spy
on the password functions and record the thread each call ran on: the loop's
own thread must never be among them. The dummy round an unknown account pays
is pinned the same way — it is the timing equalisation, and equalisation that
happens on the loop is a stall like any other.
"""

import threading

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.user import UserCreate
from app.services import auth_service, token_service
from app.services.auth_service import AuthService, authenticate_user_async
from app.services.token_service import create_password_reset_token

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _spy(real):
    """Wrap a password function so every call records its thread."""
    seen: list[threading.Thread] = []

    def spy(*args, **kwargs):
        seen.append(threading.current_thread())
        return real(*args, **kwargs)

    return spy, seen


class TestThePasswordRoundRunsOffTheEventLoop:
    async def test_the_login_check(
        self, real_async_db_session: AsyncSession, async_test_user, monkeypatch
    ):
        loop_thread = threading.current_thread()
        spy, seen = _spy(token_service.verify_password)
        monkeypatch.setattr(auth_service, 'verify_password', spy)

        result = await authenticate_user_async(
            real_async_db_session, async_test_user.email, 'testpassword123'
        )

        assert result is not None
        assert seen, 'the check never ran'
        assert loop_thread not in seen

    async def test_the_dummy_round_for_an_unknown_account(
        self, real_async_db_session: AsyncSession, monkeypatch
    ):
        loop_thread = threading.current_thread()
        spy, seen = _spy(token_service.verify_password)
        monkeypatch.setattr(auth_service, 'verify_password', spy)

        result = await authenticate_user_async(
            real_async_db_session, 'nobody@example.com', 'anypassword'
        )

        assert result is None
        assert seen, 'the equalising dummy round never ran'
        assert loop_thread not in seen

    async def test_the_register_hash(
        self, real_async_db_session: AsyncSession, monkeypatch
    ):
        loop_thread = threading.current_thread()
        spy, seen = _spy(token_service.get_password_hash)
        monkeypatch.setattr(auth_service, 'get_password_hash', spy)

        await AuthService.register_user_async(
            real_async_db_session,
            UserCreate(
                email='newcomer@example.com',
                full_name='Newcomer',
                password='Str0ng!passphrase',
            ),
        )

        assert seen, 'the hash never ran'
        assert loop_thread not in seen

    async def test_the_password_change_round(
        self, real_async_db_session: AsyncSession, async_test_user, monkeypatch
    ):
        loop_thread = threading.current_thread()
        verify_spy, verify_seen = _spy(token_service.verify_password)
        hash_spy, hash_seen = _spy(token_service.get_password_hash)
        monkeypatch.setattr(auth_service, 'verify_password', verify_spy)
        monkeypatch.setattr(auth_service, 'get_password_hash', hash_spy)

        await AuthService.update_user_profile_async(
            real_async_db_session,
            async_test_user.id,
            {
                'password': 'NewStr0ng!passphrase',
                'current_password': 'testpassword123',
            },
        )

        assert verify_seen, 'the current password was never checked'
        assert hash_seen, 'the new password was never hashed'
        assert loop_thread not in [*verify_seen, *hash_seen]

    async def test_the_reset_hash(
        self, real_async_db_session: AsyncSession, async_test_user, monkeypatch
    ):
        loop_thread = threading.current_thread()
        spy, seen = _spy(token_service.get_password_hash)
        monkeypatch.setattr(auth_service, 'get_password_hash', spy)
        token = create_password_reset_token(async_test_user.id)

        await AuthService.confirm_password_reset_async(
            real_async_db_session, token, 'NewStr0ng!passphrase'
        )

        assert seen, 'the hash never ran'
        assert loop_thread not in seen
