from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

import jwt
from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import get_async_db
from app.core.exceptions import AppException
from app.core.limiter import limiter
from app.core.logging import get_logger
from app.core.network import get_client_ip
from app.core.token_blacklist import token_blacklist
from app.i18n.service import (
    Language,
    get_current_lang,
    get_error_message,
    get_lang_from_header,
)
from app.schemas._common import LogoutResponse
from app.schemas.user import Token
from app.services.auth_service import authenticate_user_async
from app.services.token_service import (
    create_access_token,
    create_refresh_token,
    verify_token_async,
)

logger = get_logger(__name__)

router = APIRouter()

REFRESH_REUSE_GRACE_SECONDS = 10
REFRESH_ABSOLUTE_EXPIRY_GRACE_SECONDS = 86400  # 1-day grace window


def _login_limit(_key: str | None = None) -> str:
    """Resolve the login limit per request, not at import time.

    slowapi calls limit providers with no arguments when iterating dynamic
    limits (and with the bucket key on some decorated paths) — hence the
    optional parameter. Reading ``settings`` lazily keeps the value
    overridable in tests and lets a container pick up ``RATE_LIMIT_LOGIN``
    without a code rebuild.
    """
    return settings.RATE_LIMIT_LOGIN


def _refresh_limit(_key: str | None = None) -> str:
    """Same lazy-resolution pattern as ``_login_limit`` for /auth/refresh."""
    return settings.RATE_LIMIT_REFRESH


@router.post('/login', response_model=Token)
@limiter.limit(_login_limit)
async def login(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    lang: Language = Depends(get_lang_from_header),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """User login (returns JWT token and sets refresh cookie)."""
    user = await authenticate_user_async(
        db,
        form_data.username,
        form_data.password,
        client_ip=get_client_ip(request),
    )
    if not user:
        # The failed attempt the counter just recorded has to outlast the 401:
        # the exception unwinds the request's session before its own commit.
        await db.commit()
        raise AppException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code='INVALID_CREDENTIALS',
            message=get_error_message('invalid_credentials', lang),
        )
    return await start_session(response, str(user.id))


async def start_session(response: Response, user_id: str) -> Token:
    """Sign an authenticated account in: a new session's tokens and its cookie.

    Shared by the password login and the demo's one-click sandbox, so both
    hand the browser the same kind of session.
    """
    session_id = str(uuid4())

    await token_blacklist.clear_user_family(user_id, session_id)

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={'sub': user_id, 'sid': session_id},
        expires_delta=access_token_expires,
    )

    refresh_token = create_refresh_token(data={'sub': user_id, 'sid': session_id})

    response.set_cookie(
        key='refresh_token',
        value=refresh_token,
        httponly=True,
        secure=not (settings.DEBUG or settings.TESTING),
        samesite='lax',
        path='/',
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )

    return Token(access_token=access_token, token_type='bearer')


@router.post(
    '/refresh',
    response_model=Token,
    responses={
        204: {'description': 'No session to refresh — the caller holds no cookie'}
    },
)
@limiter.limit(_refresh_limit)
async def refresh_token(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Token | Response:
    """Refresh JWT token using HttpOnly cookie.

    Implements refresh token rotation: the old refresh token is blacklisted
    and a new one is issued. Reuse of a blacklisted refresh token triggers
    revocation of the entire token family for that user, unless the reuse
    occurs within a short grace window (concurrent requests from React
    StrictMode double-mount, mobile reloads, or multi-tab scenarios).

    A caller with no cookie at all is not refused: the boot probe asks this
    on every load before a session exists and "no session" is its ordinary
    answer, not an error. The refusal cases (unreadable, revoked, expired)
    stay 401 — those are answers about a session that existed.
    """
    if not refresh_token:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    is_revoked = await token_blacklist.is_revoked(refresh_token)
    user_id_from_token: str | None = None
    session_id_from_token: str | None = None
    refresh_expires_at: datetime | None = None
    try:
        payload = jwt.decode(
            refresh_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={'verify_exp': False},
        )
        user_id_from_token = payload.get('sub')
        session_id_from_token = payload.get('sid', user_id_from_token or '')
        exp_ts = payload.get('exp')
        if exp_ts:
            refresh_expires_at = datetime.fromtimestamp(exp_ts, tz=UTC)
        refresh_iat = payload.get('iat')
        if refresh_iat:
            token_age = datetime.now(tz=UTC).timestamp() - refresh_iat
            max_age_seconds = (
                settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
                + REFRESH_ABSOLUTE_EXPIRY_GRACE_SECONDS
            )
            if token_age > max_age_seconds:
                raise AppException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    code='TOKEN_ABSOLUTE_EXPIRY',
                    message=get_error_message(
                        'refresh_token_expired_grace', get_current_lang()
                    ),
                )
    except (jwt.PyJWTError, ValueError) as exc:
        logger.warning('Failed to decode refresh token for refresh: %s', exc)

    is_session_family_revoked = bool(
        user_id_from_token
        and session_id_from_token
        and await token_blacklist.is_user_revoked(
            user_id_from_token, session_id_from_token
        )
    )
    if is_revoked:
        revoked_at = await token_blacklist.get_revoked_at(refresh_token)
        if (
            not is_session_family_revoked
            and revoked_at
            and (datetime.now(tz=UTC) - revoked_at).total_seconds()
            < REFRESH_REUSE_GRACE_SECONDS
        ):
            is_revoked = False

    if is_revoked or is_session_family_revoked:
        if user_id_from_token:
            await token_blacklist.revoke_user_family(
                user_id_from_token, session_id_from_token or ''
            )
        response.delete_cookie(
            'refresh_token',
            path='/',
            secure=not (settings.DEBUG or settings.TESTING),
            httponly=True,
            samesite='lax',
        )
        raise AppException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code='TOKEN_REVOKED',
            message=get_error_message('refresh_token_revoked', get_current_lang()),
        )

    # This endpoint is the one place a refresh token is legitimate.
    user = await verify_token_async(refresh_token, db, expected_type='refresh')

    if refresh_expires_at:
        await token_blacklist.revoke(refresh_token, refresh_expires_at)

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={'sub': str(user.id), 'sid': session_id_from_token or str(user.id)},
        expires_delta=access_token_expires,
    )

    new_refresh = create_refresh_token(
        data={'sub': str(user.id), 'sid': session_id_from_token or str(user.id)}
    )
    response.set_cookie(
        key='refresh_token',
        value=new_refresh,
        httponly=True,
        secure=not (settings.DEBUG or settings.TESTING),
        samesite='lax',
        path='/',
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )

    return Token(access_token=access_token, token_type='bearer')


def _family_from(payload: dict) -> tuple[str, str] | None:
    """The (user, session) pair a token names, or ``None`` if it names neither.

    ``sid`` falls back to the user id for tokens minted before the claim
    existed, which is the same fallback ``/auth/refresh`` makes.
    """
    user_id = payload.get('sub')
    if not user_id:
        return None
    return str(user_id), str(payload.get('sid') or user_id)


@router.post('/logout', response_model=LogoutResponse)
async def logout(
    response: Response,
    request: Request,
) -> LogoutResponse:
    """
    User logout.

    - Clears the ``refresh_token`` HttpOnly cookie.
    - If a Bearer access token is present in the Authorization header, adds it
      to the Redis blacklist so ``get_current_user`` rejects it immediately
      (before JWT expiry).
    - Revokes the whole session family, so everything else minted under the
      same ``sid`` dies with it.

    That last one is what makes the button mean what it says. Blacklisting the
    two tokens in the request left every sibling of the session answering: the
    access token an earlier rotation handed out is still inside its half-hour,
    and the revoked refresh cookie was even forgiven by the rotation grace
    window, which cannot tell a deliberate logout from a double-mount race.
    The family marker can, and every path now reads it.
    """
    auth_header = request.headers.get('Authorization', '')
    token: str | None = None
    if auth_header.startswith('Bearer '):
        token = auth_header.removeprefix('Bearer ').strip() or None

    family: tuple[str, str] | None = None

    if token:
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
                options={'verify_exp': False},
            )
            family = _family_from(payload) or family
            exp_ts = payload.get('exp')
            if exp_ts:
                expires_at = datetime.fromtimestamp(exp_ts, tz=UTC)
                await token_blacklist.revoke(token, expires_at)
        except jwt.PyJWTError:  # best-effort logout; a bad token must not block
            pass

    rt = request.cookies.get('refresh_token')
    if rt:
        try:
            rt_payload = jwt.decode(
                rt,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
                options={'verify_exp': False},
            )
            family = family or _family_from(rt_payload)
            rt_exp = rt_payload.get('exp')
            if rt_exp:
                rt_expires_at = datetime.fromtimestamp(rt_exp, tz=UTC)
                await token_blacklist.revoke(rt, rt_expires_at)
        except jwt.PyJWTError:  # best-effort logout; a bad token must not block
            pass

    if family is not None:
        # Only this session: another device signed in as the same person keeps
        # its own `sid`, and logging out here is not logging out there.
        await token_blacklist.revoke_user_family(*family)

    response.delete_cookie(
        'refresh_token',
        path='/',
        secure=not (settings.DEBUG or settings.TESTING),
        httponly=True,
        samesite='lax',
    )
    return LogoutResponse(message='Logged out successfully')
