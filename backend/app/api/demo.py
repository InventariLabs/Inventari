"""The public demo's one-click sign-in: an organization of your own.

Exists only where the instance says it is a demo (``INVENTARI_DEMO``);
anywhere else the route answers 404, as if it were not there. See
``app/services/demo_sandbox_service.py`` for the pool behind it and
``docs/DEMO.md`` for the limits.
"""

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth._tokens import start_session
from app.config import settings
from app.core.deps import get_async_db
from app.core.exceptions import AppException
from app.core.limiter import limiter
from app.core.network import get_client_ip
from app.i18n.service import get_current_lang, get_error_message
from app.schemas.demo import DemoSandboxRequest
from app.schemas.user import Token
from app.services.demo_sandbox_service import (
    SandboxCapReachedError,
    SandboxPoolEmptyError,
    claim_sandbox_async,
    is_claimed_sandbox_async,
)
from app.services.token_service import (
    DEMO_SANDBOX_COOKIE_DAYS,
    create_demo_sandbox_token,
    read_demo_sandbox_subject,
)

router = APIRouter()

SANDBOX_COOKIE = 'demo_sandbox'


def _sandbox_limit(_key: str | None = None) -> str:
    """Read per request, like the login limit, so a container can change it."""
    return settings.DEMO_SANDBOX_RATE_LIMIT


def _by_address(request: Request) -> str:
    """Per address, signed in or not: "start over" comes from a signed-in visitor."""
    return f'ip:{get_client_ip(request)}'


@router.post(
    '/sandbox',
    response_model=Token,
    responses={
        404: {'description': 'This instance is not a demo'},
        429: {'description': 'Too many sandboxes: this address, or the whole day'},
        503: {'description': 'Every seeded sandbox is taken; more are on the way'},
    },
)
@limiter.limit(_sandbox_limit, key_func=_by_address)
async def open_sandbox(
    request: Request,
    response: Response,
    body: DemoSandboxRequest,
    demo_sandbox: str | None = Cookie(None),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Token:
    """Sign a demo visitor in to their own organization.

    The browser that already has one goes back to it (its cookie names the
    account) until the nightly reset deletes it; ``fresh`` asks for a new one.
    """
    if not settings.INVENTARI_DEMO:
        raise AppException(
            status_code=status.HTTP_404_NOT_FOUND,
            code='NOT_FOUND',
            message=get_error_message('not_found', get_current_lang()),
        )

    returning = read_demo_sandbox_subject(demo_sandbox) if demo_sandbox else None
    if (
        returning is not None
        and not body.fresh
        and await is_claimed_sandbox_async(db, returning)
    ):
        return await start_session(response, str(returning))

    try:
        user_id = await claim_sandbox_async(
            db,
            cap=settings.DEMO_SANDBOX_DAILY_CAP,
            preferred_language=body.preferred_language,
        )
    except SandboxCapReachedError as exc:
        raise AppException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code='DEMO_SANDBOX_CAP_REACHED',
            message=get_error_message('demo_sandbox_cap_reached', get_current_lang()),
        ) from exc
    except SandboxPoolEmptyError as exc:
        raise AppException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code='DEMO_SANDBOX_POOL_EMPTY',
            message=get_error_message('demo_sandbox_pool_empty', get_current_lang()),
        ) from exc

    response.set_cookie(
        key=SANDBOX_COOKIE,
        value=create_demo_sandbox_token(user_id),
        httponly=True,
        secure=not (settings.DEBUG or settings.TESTING),
        samesite='lax',
        # Sent to this route alone: nothing else needs to know the way back.
        path=request.url.path,
        max_age=DEMO_SANDBOX_COOKIE_DAYS * 24 * 60 * 60,
    )
    return await start_session(response, str(user_id))
