"""``inventari user create-admin`` — password reset must end earlier sessions.

Resetting a password from the CLI is an incident-response move: whoever runs
it is usually locking an attacker out. The HTTP reset paths kill existing
sessions through the credential-change marker; the CLI has no app lifespan,
so it has to wire Redis up itself.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from manage import app

runner = CliRunner()


class _FakeRedis:
    """Just enough Redis for the marker write."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.closed = False

    async def ping(self) -> bool:
        return True

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def aclose(self) -> None:
        self.closed = True


def _db_with_existing_user(user_id):
    """A sync session stand-in whose lookup finds an existing admin."""
    user = MagicMock()
    user.id = user_id
    db = MagicMock()
    db.scalars.return_value.first.return_value = user
    return db, user


class TestCreateAdminInvalidatesSessions:
    def test_reset_marks_credentials_changed(self):
        user_id = uuid4()
        db, _user = _db_with_existing_user(user_id)
        marker = AsyncMock()

        with (
            patch('app.database.SessionLocal', return_value=db),
            patch('app.cli.commands_user._mark_credentials_changed', marker),
        ):
            result = runner.invoke(
                app,
                ['user', 'create-admin', '--email', 'a@b.c', '--password', 'Passw0rd'],
            )

        assert result.exit_code == 0
        marker.assert_awaited_once_with(str(user_id))
        assert 'Earlier sessions invalidated' in result.output

    def test_marker_runs_after_the_commit(self):
        """Order matters: a marker written before the commit could outlive a
        rollback, logging everyone out without changing the password."""
        user_id = uuid4()
        db, _user = _db_with_existing_user(user_id)
        calls: list[str] = []
        db.commit.side_effect = lambda: calls.append('commit')

        async def _marker(_user_id):
            calls.append('marker')

        with (
            patch('app.database.SessionLocal', return_value=db),
            patch('app.cli.commands_user._mark_credentials_changed', _marker),
        ):
            result = runner.invoke(
                app,
                ['user', 'create-admin', '--email', 'a@b.c', '--password', 'Passw0rd'],
            )

        assert result.exit_code == 0
        assert calls == ['commit', 'marker']

    def test_failed_invalidation_is_reported_not_swallowed(self):
        """A silent failure here is exactly the bug being fixed."""
        user_id = uuid4()
        db, _user = _db_with_existing_user(user_id)

        async def _boom(_user_id):
            raise ConnectionError('Redis down')

        with (
            patch('app.database.SessionLocal', return_value=db),
            patch('app.cli.commands_user._mark_credentials_changed', _boom),
        ):
            result = runner.invoke(
                app,
                ['user', 'create-admin', '--email', 'a@b.c', '--password', 'Passw0rd'],
            )

        assert result.exit_code == 1
        assert 'could NOT be invalidated' in result.output
        assert 'stay valid' in result.output

    def test_new_user_needs_no_invalidation(self):
        """A user created just now has no sessions to kill."""
        db = MagicMock()
        db.scalars.return_value.first.return_value = None
        marker = AsyncMock()

        with (
            patch('app.database.SessionLocal', return_value=db),
            patch('app.cli.commands_user._mark_credentials_changed', marker),
        ):
            result = runner.invoke(
                app,
                [
                    'user',
                    'create-admin',
                    '--email',
                    'new@b.c',
                    '--password',
                    'Passw0rd',
                ],
            )

        assert result.exit_code == 0
        marker.assert_not_awaited()


class TestCreateAdminNamesTheInstancesSuperuser:
    """The first account is the instance's superuser, as on sign-up.

    Requests for access are decided behind ``get_superuser``. An instance
    set up with ``create-admin`` had nobody who could open them until the
    backend's next start promoted the first account.
    """

    def _create(self, db: MagicMock, *extra: str):
        with (
            patch('app.database.SessionLocal', return_value=db),
            patch('app.cli.commands_user._mark_credentials_changed', AsyncMock()),
        ):
            return runner.invoke(
                app,
                [
                    'user',
                    'create-admin',
                    '--email',
                    'first@b.c',
                    '--password',
                    'Passw0rd',
                    *extra,
                ],
            )

    def _added_user(self, db: MagicMock):
        from app.models.user import User

        return next(
            call.args[0]
            for call in db.add.call_args_list
            if isinstance(call.args[0], User)
        )

    def test_the_first_account_is_the_superuser(self):
        db = MagicMock()
        db.scalars.return_value.first.return_value = None
        db.scalar.return_value = 0

        result = self._create(db)

        assert result.exit_code == 0, result.output
        assert self._added_user(db).is_superuser is True

    def test_the_first_account_stays_an_org_admin_when_superuser_is_declined(self):
        db = MagicMock()
        db.scalars.return_value.first.return_value = None
        db.scalar.return_value = 0

        result = self._create(db, '--no-instance-superuser')

        assert result.exit_code == 0, result.output
        user = self._added_user(db)
        assert user.is_superuser is False
        assert user.role == 'admin'

    def test_a_later_admin_is_not(self):
        db = MagicMock()
        db.scalars.return_value.first.return_value = None
        db.scalar.return_value = 3

        result = self._create(db)

        assert result.exit_code == 0, result.output
        assert self._added_user(db).is_superuser is False


class TestMarkCredentialsChangedWiring:
    @pytest.mark.asyncio
    async def test_writes_the_marker_and_closes_the_connection(self):
        from app.cli.commands_user import _mark_credentials_changed
        from app.core.token_blacklist import token_blacklist

        fake = _FakeRedis()
        user_id = str(uuid4())

        with patch('redis.asyncio.from_url', return_value=fake):
            await _mark_credentials_changed(user_id)

        assert f'{token_blacklist.PREFIX}credchg:{user_id}' in fake.store
        assert fake.closed is True

    @pytest.mark.asyncio
    async def test_leaves_the_shared_blacklist_alone(self):
        """Handing this connection to the module singleton would outlive the
        command — and in-process (tests, an embedded runner) it would leave
        every later caller talking to a closed socket."""
        from app.cli.commands_user import _mark_credentials_changed
        from app.core.token_blacklist import token_blacklist

        before = token_blacklist._redis

        with patch('redis.asyncio.from_url', return_value=_FakeRedis()):
            await _mark_credentials_changed(str(uuid4()))

        assert token_blacklist._redis is before

    @pytest.mark.asyncio
    async def test_prefers_the_dedicated_critical_instance(self, monkeypatch):
        """The blacklist lives on the noeviction instance when one is
        configured — writing the marker anywhere else means nobody reads it."""
        from app.cli.commands_user import _mark_credentials_changed
        from app.config import settings

        monkeypatch.setattr(settings, 'REDIS_CRITICAL_URL', 'redis://critical:6379')
        monkeypatch.setattr(settings, 'REDIS_URL', 'redis://main:6379')
        seen: list[str] = []

        def _from_url(url, **_kwargs):
            seen.append(url)
            return _FakeRedis()

        with patch('redis.asyncio.from_url', side_effect=_from_url):
            await _mark_credentials_changed(str(uuid4()))

        assert seen == ['redis://critical:6379']

    @pytest.mark.asyncio
    async def test_falls_back_to_the_main_instance(self, monkeypatch):
        from app.cli.commands_user import _mark_credentials_changed
        from app.config import settings

        monkeypatch.setattr(settings, 'REDIS_CRITICAL_URL', '')
        monkeypatch.setattr(settings, 'REDIS_URL', 'redis://main:6379')
        seen: list[str] = []

        def _from_url(url, **_kwargs):
            seen.append(url)
            return _FakeRedis()

        with patch('redis.asyncio.from_url', side_effect=_from_url):
            await _mark_credentials_changed(str(uuid4()))

        assert seen == ['redis://main:6379']


class TestCreateAdminEnforcesThePasswordPolicy:
    """The CLI hashed whatever it was given, so `make dev-up` could create an
    account with `admin123` — a password the login screen refuses. The printed
    credentials then did not work, which cost half an hour of guessing."""

    def test_rejects_a_password_the_api_would_refuse(self):
        db = MagicMock()
        db.scalars.return_value.first.return_value = None

        with patch('app.database.SessionLocal', return_value=db):
            result = runner.invoke(
                app,
                ['user', 'create-admin', '--email', 'a@b.c', '--password', 'admin123'],
            )

        assert result.exit_code == 1
        assert 'uppercase' in result.output
        db.add.assert_not_called()

    def test_rejects_a_password_below_the_minimum_length(self):
        db = MagicMock()
        db.scalars.return_value.first.return_value = None

        with patch('app.database.SessionLocal', return_value=db):
            result = runner.invoke(
                app,
                ['user', 'create-admin', '--email', 'a@b.c', '--password', 'Ab1'],
            )

        assert result.exit_code == 1
        assert '8 characters' in result.output
        db.add.assert_not_called()

    def test_rejects_a_password_past_the_byte_ceiling(self):
        """bcrypt refuses passwords longer than 72 bytes instead of
        truncating them, so an account the CLI created with one could never
        log in — the policy the API applies is the policy here."""
        #: 73 bytes in UTF-8: 35 two-byte letters plus 'Aa1'.
        past_the_ceiling = 'Ą' * 35 + 'Aa1'
        db = MagicMock()
        db.scalars.return_value.first.return_value = None

        with patch('app.database.SessionLocal', return_value=db):
            result = runner.invoke(
                app,
                [
                    'user',
                    'create-admin',
                    '--email',
                    'a@b.c',
                    '--password',
                    past_the_ceiling,
                ],
            )

        assert result.exit_code == 1
        assert 'bytes' in result.output
        db.add.assert_not_called()

    def test_accepts_the_development_default(self):
        """`DEV_ADMIN_PASSWORD` in the Makefile has to pass this check, or
        `make dev-up` fails on a fresh checkout."""
        db = MagicMock()
        db.scalars.return_value.first.return_value = None

        with patch('app.database.SessionLocal', return_value=db):
            result = runner.invoke(
                app,
                ['user', 'create-admin', '--email', 'a@b.c', '--password', 'Admin123'],
            )

        assert result.exit_code == 0
        db.add.assert_called()


class TestCreateAdminRefusesKnownWeakPasswordsInProduction:
    """The Makefile seeds `Admin123` for the throwaway dev stack; on anything
    production-shaped that same password is a standing credential. The command
    must refuse the known-weak list when DEBUG and TESTING are both off — the
    same dev signal the SECRET_KEY gate in app.config uses — and name the way
    out: a strong password, or the explicit override flag.
    """

    @staticmethod
    def _production_settings(monkeypatch):
        """Simulate a deployed install: dev/test signals off. The command reads
        the settings attributes at call time, so attribute patching (not
        os.environ, which conftest pins to TESTING=true) is the seam."""
        from app.config import settings

        monkeypatch.setattr(settings, 'DEBUG', False)
        monkeypatch.setattr(settings, 'TESTING', False)

    def test_refuses_the_makefile_default_in_production(self, monkeypatch):
        self._production_settings(monkeypatch)
        db = MagicMock()
        db.scalars.return_value.first.return_value = None

        with patch('app.database.SessionLocal', return_value=db):
            result = runner.invoke(
                app,
                ['user', 'create-admin', '--email', 'a@b.c', '--password', 'Admin123'],
            )

        assert result.exit_code == 1
        assert 'known-weak' in result.output
        assert '--allow-weak-password' in result.output
        db.add.assert_not_called()

    @pytest.mark.parametrize(
        'weak',
        ['Admin123', 'admin', 'password', 'Password123', 'admin123', 'changeme'],
    )
    def test_refuses_each_known_weak_password_in_production(self, monkeypatch, weak):
        """The blocklist runs ahead of the complexity policy, so even entries
        the policy would reject anyway get the production-shaped refusal."""
        self._production_settings(monkeypatch)
        db = MagicMock()
        db.scalars.return_value.first.return_value = None

        with patch('app.database.SessionLocal', return_value=db):
            result = runner.invoke(
                app,
                ['user', 'create-admin', '--email', 'a@b.c', '--password', weak],
            )

        assert result.exit_code == 1
        assert 'known-weak' in result.output
        db.add.assert_not_called()

    def test_accepts_a_strong_password_in_production(self, monkeypatch):
        """The gate is a blocklist, not a lockout: operators still create the
        first admin on a real deployment (DEPLOYMENT.md tells them to)."""
        self._production_settings(monkeypatch)
        db = MagicMock()
        db.scalars.return_value.first.return_value = None

        with patch('app.database.SessionLocal', return_value=db):
            result = runner.invoke(
                app,
                [
                    'user',
                    'create-admin',
                    '--email',
                    'a@b.c',
                    '--password',
                    'Str0ng!Unique-Pass',
                ],
            )

        assert result.exit_code == 0
        db.add.assert_called()

    def test_debug_mode_keeps_the_makefile_default_frictionless(self, monkeypatch):
        """DEBUG=true is the dev stack's signal (Makefile dev-up writes it into
        .env); there the seed password must keep working, no flag needed."""
        from app.config import settings

        monkeypatch.setattr(settings, 'DEBUG', True)
        db = MagicMock()
        db.scalars.return_value.first.return_value = None

        with patch('app.database.SessionLocal', return_value=db):
            result = runner.invoke(
                app,
                ['user', 'create-admin', '--email', 'a@b.c', '--password', 'Admin123'],
            )

        assert result.exit_code == 0
        db.add.assert_called()

    def test_allow_weak_password_overrides_the_refusal(self, monkeypatch):
        """The override has to be explicit — an operator typing a flag knows —
        mirroring the ACK_UNSAFE settings the other production gates use."""
        self._production_settings(monkeypatch)
        db = MagicMock()
        db.scalars.return_value.first.return_value = None

        with patch('app.database.SessionLocal', return_value=db):
            result = runner.invoke(
                app,
                [
                    'user',
                    'create-admin',
                    '--email',
                    'a@b.c',
                    '--password',
                    'Admin123',
                    '--allow-weak-password',
                ],
            )

        assert result.exit_code == 0
        db.add.assert_called()
