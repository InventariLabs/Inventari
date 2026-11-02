from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import bcrypt
import jwt
from fastapi import status
from jwt.exceptions import PyJWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import ServiceRejectionError, catalogue_status_refusal
from app.i18n.service import get_current_lang, get_error_message
from app.models.user import User
from app.schemas.user import PASSWORD_MAX_BYTES, TokenData


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash.

    A password past the bcrypt byte ceiling answers False instead of raising:
    no stored hash can match it (hashing refuses such values), and a login
    attempt with one must behave exactly like a wrong password. The bcrypt
    round is still paid, with a short stand-in, so the answer is not
    measurably faster than a wrong password's — the timing oracle the
    uniform 401 closed stays closed.
    """
    password_bytes = plain_password.encode('utf-8')
    if len(password_bytes) > PASSWORD_MAX_BYTES:
        bcrypt.checkpw(b'past-the-bcrypt-ceiling', hashed_password.encode('utf-8'))
        return False
    return bcrypt.checkpw(password_bytes, hashed_password.encode('utf-8'))


def get_password_hash(password: str) -> str:
    """Hash a password.

    Uses minimal bcrypt rounds in TESTING mode — test fixtures hash the same
    password thousands of times per suite run, and cost-12 hashing dominates
    fixture setup time.

    A password past the bcrypt byte ceiling is refused with our sentence
    before the library gets to raise its own: the value never reaches a
    reader-carrying door unvalidated, and if a path misses its schema check,
    the reader still sees the policy, not the library.
    """
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > PASSWORD_MAX_BYTES:
        raise ServiceRejectionError('password_too_long', max_bytes=PASSWORD_MAX_BYTES)
    salt = bcrypt.gensalt(rounds=4) if settings.TESTING else bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


# JWT ``type`` claim values (not secrets — ruff's S105 heuristic
# flags any constant whose name ends in TOKEN).
ACCESS_TOKEN_TYPE = 'access'  # noqa: S105
REFRESH_TOKEN_TYPE = 'refresh'  # noqa: S105


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a new JWT token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    # ``iat`` lets a credential change invalidate exactly the tokens
    # minted before it, without killing the ones issued afterwards.
    # ``type`` keeps a refresh token from passing as a Bearer access
    # token — same shape, thirty times the lifetime.
    to_encode.update(
        {'exp': expire, 'iat': datetime.now(UTC), 'type': ACCESS_TOKEN_TYPE}
    )
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a new Refresh Token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update(  # iat drives credential-change checks, type the kind
        {'exp': expire, 'iat': datetime.now(UTC), 'type': REFRESH_TOKEN_TYPE}
    )
    to_encode.setdefault('jti', str(uuid4()))
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt


PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = 30


def create_password_reset_token(user_id: UUID) -> str:
    """Short-lived JWT for password reset.

    Carries a ``type: 'password_reset'`` claim so the same secret key cannot
    be confused with access/refresh tokens. A unique ``jti`` lets us identify
    individual reset attempts in logs.
    """
    expire = datetime.now(UTC) + timedelta(minutes=PASSWORD_RESET_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        'sub': str(user_id),
        'exp': expire,
        'type': 'password_reset',
        'jti': str(uuid4()),
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


DEMO_SANDBOX_COOKIE_DAYS = 2


def create_demo_sandbox_token(user_id: UUID) -> str:
    """The way back into a demo visitor's own sandbox, kept in a cookie.

    Its own ``type`` keeps it from passing as an access or refresh token. It
    outlives the night on purpose: the reset deletes the account it names, and
    a token naming nobody simply leads to a fresh sandbox.
    """
    expire = datetime.now(UTC) + timedelta(days=DEMO_SANDBOX_COOKIE_DAYS)
    to_encode = {'sub': str(user_id), 'exp': expire, 'type': 'demo_sandbox'}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def read_demo_sandbox_subject(token: str) -> UUID | None:
    """The account a sandbox cookie names, or None for anything else."""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
    except PyJWTError:
        return None
    if payload.get('type') != 'demo_sandbox':
        return None
    try:
        return UUID(str(payload.get('sub')))
    except ValueError:
        return None


def read_password_reset_claims(token: str) -> tuple[UUID, str, datetime] | None:
    """Return ``(user_id, jti, expires_at)`` for a valid reset token.

    The ``jti`` and the expiry are what let the reset flow burn the token
    after its first use — a leaked reset link used to work for the full 30
    minutes, however many times it was replayed.

    Returns None on any failure (invalid signature, wrong type, expired,
    bad UUID) so callers can decide how to react.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
    except PyJWTError:
        return None
    if payload.get('type') != 'password_reset':
        return None
    sub = payload.get('sub')
    jti = payload.get('jti')
    exp = payload.get('exp')
    if not isinstance(sub, str) or not sub or not isinstance(jti, str) or not exp:
        return None
    try:
        return UUID(sub), jti, datetime.fromtimestamp(exp, tz=UTC)
    except ValueError:
        return None


async def verify_token_async(
    token: str, db: AsyncSession, *, expected_type: str = ACCESS_TOKEN_TYPE
) -> User:
    """Resolve the user behind *token*, or raise 401.

    ``expected_type`` is enforced, so a refresh token sent as
    ``Authorization: Bearer`` no longer authenticates a request — it used to,
    which handed an attacker a 30-day access token outside the rotation
    machinery. Tokens minted before this claim existed carry no ``type`` and
    are rejected: the deployment logs everyone out once, a one-time cost of
    closing the hole.
    """
    credentials_exception = catalogue_status_refusal(
        'token_invalid',
        status.HTTP_401_UNAUTHORIZED,
        headers={'WWW-Authenticate': 'Bearer'},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str | None = payload.get('sub')
        if user_id is None:
            raise credentials_exception
        if payload.get('type') != expected_type:
            raise credentials_exception
        token_data = TokenData(user_id=UUID(user_id))
    except (PyJWTError, ValueError):
        raise credentials_exception from None

    # A password reset/change invalidates every token minted before
    # it — including a refresh token an attacker stole before the reset.
    # Imported here because token_blacklist pulls in app.config at call time.
    from app.core.token_blacklist import token_blacklist

    if await token_blacklist.is_issued_before_credential_change(
        user_id, payload.get('iat')
    ):
        raise credentials_exception

    # And the session family this token belongs to. The marker was consulted
    # only by /auth/refresh and the media cookie, so reuse detection — the one
    # moment the system believes a session is in someone else's hands — left
    # the access tokens it had already minted answering for their full
    # lifetime. A GDPR delete left the same gap.
    #
    # One more EXISTS on a connection this call already uses twice (the
    # per-token blacklist and the credential-change marker); the check that
    # can deny access is not the place to trade correctness for a round trip.
    # Tokens minted before ``sid`` existed fall back to the user-wide key,
    # which is the one the API-key flow honours.
    if await token_blacklist.is_user_revoked(user_id, payload.get('sid') or ''):
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == token_data.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception

    # Check if user is blocked (admin/SaaS block — fail-fast with a reason)
    if user.is_blocked:
        raise catalogue_status_refusal(
            'user_blocked',
            status.HTTP_403_FORBIDDEN,
            reason=user.blocking_reason
            or get_error_message('user_blocked_no_reason', get_current_lang()),
        )

    # Check if user is deactivated: a deactivated user must not keep
    # API access via an already-issued token until natural expiry. Login checks
    # is_active separately; this enforces it on every authenticated request.
    if not user.is_active:
        raise catalogue_status_refusal(
            'token_invalid',
            status.HTTP_401_UNAUTHORIZED,
            headers={'WWW-Authenticate': 'Bearer'},
        )

    return user
