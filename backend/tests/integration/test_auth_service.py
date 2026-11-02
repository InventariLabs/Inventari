"""
Integration tests for auth_service functions.

Tests cover:
- Password hashing and verification
- Access token and refresh token creation
- Token verification with JWT validation
- User blocking detection
- Token blacklisting
"""

from datetime import timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.token_service import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
    verify_token_async,
)


@pytest.mark.integration
@pytest.mark.asyncio
class TestAuthService:
    """AuthService integration tests."""

    async def test_verify_password_correct(self):
        """Test that correct password verifies successfully."""
        plain_password = 'MySecurePassword123!'
        hashed = get_password_hash(plain_password)

        result = verify_password(plain_password, hashed)
        assert result is True

    async def test_verify_password_incorrect(self):
        """Test that incorrect password fails verification."""
        plain_password = 'CorrectPassword123'
        wrong_password = 'WrongPassword123'
        hashed = get_password_hash(plain_password)

        result = verify_password(wrong_password, hashed)
        assert result is False

    async def test_verify_password_empty_vs_hashed(self):
        """Test that empty password doesn't match hashed password."""
        plain_password = 'MyPassword123'
        hashed = get_password_hash(plain_password)

        result = verify_password('', hashed)
        assert result is False

    async def test_get_password_hash_returns_string(self):
        """Test that password hashing returns a string."""
        password = 'TestPassword123'
        hashed = get_password_hash(password)

        assert isinstance(hashed, str)
        assert len(hashed) > 0

    async def test_get_password_hash_creates_different_hashes(self):
        """Test that same password creates different hashes (salt-based)."""
        password = 'TestPassword123'
        hash1 = get_password_hash(password)
        hash2 = get_password_hash(password)

        # Same password should create different hashes (bcrypt uses random salt)
        assert hash1 != hash2

    async def test_get_password_hash_is_verifiable(self):
        """Test that hashed password can be verified."""
        password = 'MySecurePassword'
        hashed = get_password_hash(password)

        # Verify the hash works
        result = verify_password(password, hashed)
        assert result is True

    async def test_create_access_token_basic(self):
        """Test creating access token with default expiration."""
        data = {'sub': str(uuid4())}
        token = create_access_token(data)

        assert isinstance(token, str)
        assert len(token) > 0

        # Decode to verify it's valid JWT
        decoded = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        assert decoded['sub'] == data['sub']
        assert 'exp' in decoded

    async def test_create_refresh_token_generates_unique_token_each_time(self):
        """Refresh token rotation must produce a new token even within one second."""
        data = {'sub': str(uuid4()), 'sid': str(uuid4())}

        first = create_refresh_token(data)
        second = create_refresh_token(data)

        assert second != first

    async def test_create_access_token_with_custom_expiration(self):
        """Test creating access token with custom expiration."""
        user_id = str(uuid4())
        data = {'sub': user_id}
        custom_expires = timedelta(hours=2)

        token = create_access_token(data, expires_delta=custom_expires)

        decoded = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        assert decoded['sub'] == user_id

    async def test_create_access_token_expiration_in_future(self):
        """Test that access token expiration is in the future."""
        from datetime import UTC, datetime

        data = {'sub': str(uuid4())}
        token = create_access_token(data)

        decoded = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        exp_timestamp = decoded['exp']
        exp_datetime = datetime.fromtimestamp(exp_timestamp, tz=UTC)
        now = datetime.now(UTC)

        assert exp_datetime > now

    async def test_create_refresh_token_basic(self):
        """Test creating refresh token."""
        data = {'sub': str(uuid4())}
        token = create_refresh_token(data)

        assert isinstance(token, str)
        assert len(token) > 0

        # Decode to verify it's valid JWT
        decoded = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        assert decoded['sub'] == data['sub']
        assert 'exp' in decoded
        assert 'jti' in decoded

    async def test_create_refresh_token_with_custom_expiration(self):
        """Test creating refresh token with custom expiration."""
        user_id = str(uuid4())
        data = {'sub': user_id}
        custom_expires = timedelta(days=30)

        token = create_refresh_token(data, expires_delta=custom_expires)

        decoded = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        assert decoded['sub'] == user_id

    async def test_create_refresh_token_longer_expiration(self):
        """Test that refresh token has longer expiration than typical access."""
        from datetime import UTC, datetime

        data = {'sub': str(uuid4())}
        access = create_access_token(data)
        refresh = create_refresh_token(data)

        access_decoded = jwt.decode(
            access,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        refresh_decoded = jwt.decode(
            refresh,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )

        access_exp = datetime.fromtimestamp(access_decoded['exp'], tz=UTC)
        refresh_exp = datetime.fromtimestamp(refresh_decoded['exp'], tz=UTC)

        # Refresh token should expire after access token
        assert refresh_exp > access_exp

    async def test_verify_token_valid(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """Test verifying a valid token."""
        data = {'sub': str(async_test_user.id)}
        token = create_access_token(data)

        user = await verify_token_async(token, real_async_db_session)

        assert user is not None
        assert user.id == async_test_user.id
        assert user.email == async_test_user.email

    async def test_verify_token_invalid_jwt_format(
        self, real_async_db_session: AsyncSession
    ):
        """Test that invalid JWT format raises exception."""
        with pytest.raises(HTTPException) as exc_info:
            await verify_token_async('not.a.valid.jwt.format', real_async_db_session)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_verify_token_missing_sub_claim(
        self, real_async_db_session: AsyncSession
    ):
        """Test that token without 'sub' claim raises exception."""
        data = {'some_field': 'value'}
        token = jwt.encode(data, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

        with pytest.raises(HTTPException) as exc_info:
            await verify_token_async(token, real_async_db_session)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_verify_token_expired(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """Test that expired token raises exception."""
        data = {'sub': str(async_test_user.id)}
        expired_token = create_access_token(data, expires_delta=timedelta(seconds=-1))

        with pytest.raises(HTTPException) as exc_info:
            await verify_token_async(expired_token, real_async_db_session)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_verify_token_nonexistent_user(
        self, real_async_db_session: AsyncSession
    ):
        """Test that token for nonexistent user raises exception."""
        fake_user_id = uuid4()
        data = {'sub': str(fake_user_id)}
        token = create_access_token(data)

        with pytest.raises(HTTPException) as exc_info:
            await verify_token_async(token, real_async_db_session)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_verify_token_blocked_user(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """Test that blocked user raises exception with appropriate message."""
        async_test_user.is_blocked = True
        async_test_user.blocking_reason = 'Violated terms of service'
        await real_async_db_session.flush()

        data = {'sub': str(async_test_user.id)}
        token = create_access_token(data)

        with pytest.raises(HTTPException) as exc_info:
            await verify_token_async(token, real_async_db_session)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    async def test_verify_token_blocked_user_no_reason(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """Test blocked user without blocking reason."""
        async_test_user.is_blocked = True
        async_test_user.blocking_reason = None
        await real_async_db_session.flush()

        data = {'sub': str(async_test_user.id)}
        token = create_access_token(data)

        with pytest.raises(HTTPException) as exc_info:
            await verify_token_async(token, real_async_db_session)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        # Should use default "No reason provided"
        assert exc_info.value.detail['code'] == 'USER_BLOCKED'
        assert 'No reason provided' in exc_info.value.detail['message']

    async def test_verify_token_inactive_user_rejected(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """A deactivated user's valid token must be rejected.

        verify_token_async previously checked only is_blocked, so a deactivated
        user kept API access until the token naturally expired.
        """
        async_test_user.is_active = False
        await real_async_db_session.flush()

        data = {'sub': str(async_test_user.id)}
        token = create_access_token(data)

        with pytest.raises(HTTPException) as exc_info:
            await verify_token_async(token, real_async_db_session)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_verify_token_rejects_refresh_token_as_access(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """A refresh token must NOT authenticate a normal request.

        This test asserted the opposite until the type claim — the two kinds were
        indistinguishable, so a refresh token in an Authorization header was a
        30-day access token outside the rotation machinery.
        """
        data = {'sub': str(async_test_user.id)}
        refresh_token = create_refresh_token(data)

        with pytest.raises(HTTPException) as exc_info:
            await verify_token_async(refresh_token, real_async_db_session)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_verify_token_accepts_refresh_token_when_expected(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """The refresh endpoint asks for the refresh type explicitly."""
        refresh_token = create_refresh_token({'sub': str(async_test_user.id)})

        user = await verify_token_async(
            refresh_token, real_async_db_session, expected_type='refresh'
        )

        assert user.id == async_test_user.id

    async def test_password_hash_format_is_bcrypt(self):
        """Test that password hash is valid bcrypt format."""
        password = 'MyPassword123'
        hashed = get_password_hash(password)

        # Bcrypt hashes start with $2
        assert hashed.startswith('$2')

    async def test_multiple_users_can_have_same_password_different_hash(
        self, real_async_db_session: AsyncSession
    ):
        """Test that different users with same password have different hashes."""
        password = 'CommonPassword123'
        hash1 = get_password_hash(password)
        hash2 = get_password_hash(password)

        # Different hashes for same password (bcrypt salt)
        assert hash1 != hash2

        # Both verify against original password
        assert verify_password(password, hash1)
        assert verify_password(password, hash2)

    async def test_verify_token_claims_preserved(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """Test that custom claims in token are preserved."""
        user_id = str(async_test_user.id)
        data = {
            'sub': user_id,
            'custom_field': 'custom_value',
            'another_field': 123,
        }
        token = create_access_token(data)

        # Decode to check custom fields
        decoded = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        assert decoded['sub'] == user_id
        assert decoded['custom_field'] == 'custom_value'
        assert decoded['another_field'] == 123

        # verify_token returns user by 'sub' claim
        user = await verify_token_async(token, real_async_db_session)
        assert user.id == async_test_user.id
