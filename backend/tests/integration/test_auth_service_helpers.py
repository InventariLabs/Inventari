"""
Integration tests for auth_service helper functions.

Covers: authenticate_user_async, _is_locked_out,
_record_failed_attempt_async, _clear_failed_attempts_async.
"""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.user import User
from app.services.auth_service import (
    MAX_FAILED_ATTEMPTS,
    _clear_failed_attempts_async,
    _is_locked_out,
    _record_failed_attempt_async,
    authenticate_user_async,
)


@pytest.mark.integration
class TestCheckAccountLockout:
    def test_no_lockout_when_no_failed_attempts(self, test_user):
        test_user.failed_login_count = 0
        test_user.locked_until = None
        assert _is_locked_out(test_user) is False

    def test_no_lockout_when_below_threshold(self, test_user):
        test_user.failed_login_count = MAX_FAILED_ATTEMPTS - 1
        test_user.locked_until = None
        assert _is_locked_out(test_user) is False

    def test_reports_lockout_when_locked_and_not_expired(self, test_user):
        """Reports, never raises — the router must not turn account
        state into a distinguishable response before any password check."""
        from datetime import UTC, datetime, timedelta

        test_user.failed_login_count = MAX_FAILED_ATTEMPTS
        test_user.locked_until = datetime.now(UTC) + timedelta(minutes=10)
        assert _is_locked_out(test_user) is True

    def test_no_lockout_when_lock_expired(self, test_user):
        from datetime import UTC, datetime, timedelta

        test_user.failed_login_count = MAX_FAILED_ATTEMPTS
        test_user.locked_until = datetime.now(UTC) - timedelta(minutes=1)
        assert _is_locked_out(test_user) is False


@pytest.mark.integration
class TestRecordFailedAttempt:
    @pytest.mark.asyncio
    async def test_increments_count(self, real_async_db_session, async_test_user):
        db = real_async_db_session
        async_test_user.failed_login_count = 2
        await _record_failed_attempt_async(db, async_test_user)
        assert async_test_user.failed_login_count == 3
        assert async_test_user.locked_until is None

    @pytest.mark.asyncio
    async def test_locks_account_at_threshold(
        self, real_async_db_session, async_test_user
    ):
        db = real_async_db_session
        async_test_user.failed_login_count = MAX_FAILED_ATTEMPTS - 1
        await _record_failed_attempt_async(db, async_test_user)
        assert async_test_user.failed_login_count == MAX_FAILED_ATTEMPTS
        assert async_test_user.locked_until is not None

    @pytest.mark.asyncio
    async def test_increments_from_none(self, real_async_db_session, async_test_user):
        db = real_async_db_session
        async_test_user.failed_login_count = None
        await _record_failed_attempt_async(db, async_test_user)
        assert async_test_user.failed_login_count == 1


@pytest.mark.integration
class TestClearFailedAttempts:
    @pytest.mark.asyncio
    async def test_clears_when_count_nonzero(
        self, real_async_db_session, async_test_user
    ):
        from datetime import UTC, datetime, timedelta

        db = real_async_db_session
        async_test_user.failed_login_count = 5
        async_test_user.locked_until = datetime.now(UTC) + timedelta(minutes=10)
        await _clear_failed_attempts_async(db, async_test_user)
        assert async_test_user.failed_login_count == 0
        assert async_test_user.locked_until is None

    @pytest.mark.asyncio
    async def test_noop_when_count_zero(self, real_async_db_session, async_test_user):
        db = real_async_db_session
        async_test_user.failed_login_count = 0
        async_test_user.locked_until = None
        await _clear_failed_attempts_async(db, async_test_user)
        assert async_test_user.failed_login_count == 0


@pytest.mark.integration
class TestAuthenticateUser:
    @pytest.mark.asyncio
    async def test_authenticate_valid_credentials(
        self, real_async_db_session, async_test_user
    ):
        db = real_async_db_session
        result = await authenticate_user_async(
            db, async_test_user.email, 'testpassword123'
        )
        assert result is not None
        assert result.id == async_test_user.id

    @pytest.mark.asyncio
    async def test_authenticate_wrong_password(
        self, real_async_db_session, async_test_user
    ):
        db = real_async_db_session
        result = await authenticate_user_async(
            db, async_test_user.email, 'wrongpassword'
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_nonexistent_email(self, real_async_db_session):
        db = real_async_db_session
        result = await authenticate_user_async(db, 'nobody@example.com', 'anypassword')
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_inactive_user_is_refused(
        self, real_async_db_session, async_test_user
    ):
        """Refused like any other failure — no distinguishing signal."""
        db = real_async_db_session
        async_test_user.is_active = False
        await db.flush()
        assert (
            await authenticate_user_async(db, async_test_user.email, 'testpassword123')
            is None
        )

    @pytest.mark.asyncio
    async def test_authenticate_locked_user_is_refused(
        self, real_async_db_session, async_test_user
    ):
        """The lockout still holds — with the correct password, and silently."""
        from datetime import UTC, datetime, timedelta

        db = real_async_db_session
        async_test_user.failed_login_count = MAX_FAILED_ATTEMPTS
        async_test_user.locked_until = datetime.now(UTC) + timedelta(minutes=10)
        await db.flush()
        assert (
            await authenticate_user_async(db, async_test_user.email, 'testpassword123')
            is None
        )

    @pytest.mark.asyncio
    async def test_authenticate_blocked_user_is_refused(
        self, real_async_db_session, async_test_user
    ):
        """A blocked user must not obtain a fresh token at login,
        and must not learn from the response that they are blocked.
        """
        db = real_async_db_session
        async_test_user.is_blocked = True
        async_test_user.blocking_reason = 'Policy violation'
        await db.flush()
        assert (
            await authenticate_user_async(db, async_test_user.email, 'testpassword123')
            is None
        )

    @pytest.mark.asyncio
    async def test_authenticate_clears_failed_on_success(
        self, real_async_db_session, async_test_user
    ):
        db = real_async_db_session
        async_test_user.failed_login_count = 3
        await db.flush()
        result = await authenticate_user_async(
            db, async_test_user.email, 'testpassword123'
        )
        assert result is not None
        assert result.failed_login_count == 0

    @pytest.mark.asyncio
    async def test_authenticate_records_failed_on_bad_password(
        self, real_async_db_session, async_test_user
    ):
        db = real_async_db_session
        async_test_user.failed_login_count = 0
        await db.flush()
        await authenticate_user_async(db, async_test_user.email, 'wrongpassword')
        await db.refresh(async_test_user)
        assert async_test_user.failed_login_count == 1

    @pytest.mark.asyncio
    async def test_authenticate_records_failed_on_a_password_past_the_byte_ceiling(
        self, real_async_db_session, async_test_user
    ):
        """A past-the-ceiling password answers like a wrong password in full:
        the attempt is counted, so it feeds the lockout the same way."""
        #: 73 bytes in UTF-8: 35 two-byte letters plus 'Aa1'.
        past_the_ceiling = 'Ą' * 35 + 'Aa1'
        db = real_async_db_session
        async_test_user.failed_login_count = 0
        await db.flush()
        await authenticate_user_async(db, async_test_user.email, past_the_ceiling)
        await db.refresh(async_test_user)
        assert async_test_user.failed_login_count == 1

    @pytest.mark.asyncio
    async def test_locked_account_still_pays_for_the_hash(
        self, real_async_db_session, async_test_user, monkeypatch
    ):
        """Returning early on a lockout skipped bcrypt, so a locked account
        answered measurably faster than a wrong password — the response time
        leaked what the uniform 401 is there to hide."""
        from datetime import UTC, datetime, timedelta

        from app.services import auth_service

        attempted: list[str] = []
        real_verify = auth_service.verify_password

        def _counting_verify(plain: str, hashed: str) -> bool:
            attempted.append(plain)
            return real_verify(plain, hashed)

        monkeypatch.setattr(auth_service, 'verify_password', _counting_verify)

        db = real_async_db_session
        async_test_user.failed_login_count = MAX_FAILED_ATTEMPTS
        async_test_user.locked_until = datetime.now(UTC) + timedelta(minutes=10)
        await db.flush()

        assert (
            await authenticate_user_async(db, async_test_user.email, 'testpassword123')
            is None
        )
        assert attempted == ['testpassword123']


@pytest.mark.integration
class TestConcurrentFailedAttemptsAreNotLost:
    @pytest.mark.asyncio
    async def test_parallel_failures_all_count(
        self, real_async_db_session, async_test_user
    ):
        """Five failures landing together must leave the counter at five.

        Each caller used to load the row, add one in Python and write the
        sum back: four of the five increments were overwritten by the fifth
        writer, so the lockout arrived later than the threshold said. The
        sessions below load the row before any of them writes — the window
        the old read-add-write could not survive — and the counter must come
        back as the number of failures, not as one.
        """
        failures = 5
        db = real_async_db_session
        async_test_user.failed_login_count = 0
        await db.commit()

        engine = create_async_engine(
            settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1),
            echo=False,
            poolclass=NullPool,
        )
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        sessions = [factory() for _ in range(failures)]

        async def fail_once(session: AsyncSession, user: User) -> None:
            await _record_failed_attempt_async(session, user)
            # As the login route does before its 401.
            await session.commit()

        try:
            users = [
                await session.get(User, async_test_user.id) for session in sessions
            ]
            await asyncio.gather(
                *(
                    fail_once(session, user)
                    for session, user in zip(sessions, users, strict=True)
                )
            )
        finally:
            for session in sessions:
                await session.close()
            await engine.dispose()

        await db.refresh(async_test_user)
        assert async_test_user.failed_login_count == failures
