from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_superuser
from app.config import settings
from app.core.deps import get_async_db
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    catalogue_refusal,
)
from app.core.limiter import limiter
from app.core.logging import get_logger
from app.i18n import Language
from app.i18n.service import get_current_lang, get_error_message
from app.schemas._common import (
    InitStatusResponse,
    RegistrationApproveResponse,
    RegistrationRequestResponse,
)
from app.schemas.pagination import PaginatedResponse
from app.schemas.user import (
    RegistrationComplete,
    RegistrationRequestCreate,
    UserCreate,
)
from app.schemas.user import (
    RegistrationRequest as RegistrationRequestSchema,
)
from app.schemas.user import (
    User as UserSchema,
)
from app.services._org_membership import open_invitation
from app.services.auth_service import AuthService

logger = get_logger(__name__)

router = APIRouter()


@router.post(
    '/register', response_model=UserSchema, status_code=status.HTTP_201_CREATED
)
@limiter.limit('3/hour')
async def register(
    request: Request,
    user_in: UserCreate,
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Register a user directly — bootstrap or invite only.

    Two callers are legitimate here, and the UI only ever produces those two:
    the very first account on an empty installation, and someone holding a
    valid invite code. Everyone else goes through ``/registration-request``,
    which an operator approves.

    The gate runs before the address is looked up, so a caller without an
    invite gets the same answer whether or not the address has an account —
    otherwise this endpoint doubles as an oracle listing who is here. The 409
    below is reachable only once the caller has proved they hold a valid
    invite, which is not a position an anonymous prober is in.
    """
    # An account created without an explicit choice inherits the language the
    # request arrived in. The sign-in screen already speaks it; the onboarding
    # that follows used to switch to English because the schema defaulted
    # there, and the reader had to find the picker to get their own language
    # back. An explicit choice from the form still wins.
    if user_in.preferred_language is None:
        user_in.preferred_language = get_current_lang()

    # An empty users table is the bootstrap window on an ordinary install. On a
    # demo it is the gap between a reset dropping the schema and re-creating
    # the demo account, and whoever registered in it would own the instance:
    # the demo account is created by the reset alone.
    is_bootstrap = (
        await AuthService.get_user_count_async(db) == 0 and not settings.INVENTARI_DEMO
    )
    if not is_bootstrap and (
        not user_in.invite_code
        or not await AuthService.find_usable_invitation_async(
            db, user_in.invite_code, user_in.email
        )
    ):
        # A link that is alive but was minted for another address says so:
        # the visitor holds a valid code, and "invalid invitation" sent them
        # off to ask for a fresh one when a corrected address was all it took.
        # Only someone holding an open code reaches this answer, so it is no
        # oracle for which addresses are invited.
        reason = (
            'organization_invite_wrong_email'
            if user_in.invite_code and await open_invitation(db, user_in.invite_code)
            else 'organization_invite_invalid'
        )
        raise catalogue_refusal(reason, lang=user_in.preferred_language)

    if await AuthService.email_exists_async(db, user_in.email):
        raise ConflictException(
            code='REGISTRATION_FAILED',
            message=get_error_message(
                'registration_failed', user_in.preferred_language
            ),
        )

    return await AuthService.register_user_async(db, user_in)


@router.get('/init-status', response_model=InitStatusResponse)
async def get_init_status(db: AsyncSession = Depends(get_async_db, scope='function')):
    """Check if the system has any users, where the demo's inbox is, and who runs it."""
    # A demo always reads as initialized: it is never set up by the first
    # visitor (``/register`` refuses that), so the sign-in screen must not offer
    # to. A comment, not docstring text: the docstring is the OpenAPI summary.
    count = await AuthService.get_user_count_async(db)
    return {
        'is_initialized': count > 0 or settings.INVENTARI_DEMO,
        'is_demo': settings.INVENTARI_DEMO,
        'email_delivery_configured': await AuthService.mail_delivery_available_async(
            db
        ),
        'demo_inbox_url': settings.DEMO_INBOX_URL or None,
        'operator_name': settings.OPERATOR_NAME.strip() or None,
        'operator_contact': settings.OPERATOR_CONTACT.strip() or None,
    }


@router.post(
    '/registration-request',
    response_model=RegistrationRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit('3/hour')
async def create_registration_request(
    request: Request,
    request_in: RegistrationRequestCreate,
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Create a new registration request.

    Answers the same way whichever branch runs: this endpoint is
       public and anonymous, so a 409 for a taken address — or a distinct message
       for one that already has a request on file — would turn it into an oracle
       telling an attacker which addresses hold accounts here. Password reset
       follows the same rule.
    """
    # A demo has no instance superuser, so a request lands where nobody can
    # read it: the visitor would be told it was submitted and keep waiting,
    # and the instance would hold a stranger's name and address until the
    # nightly reset. Visitors need no account there, and the sign-in screen
    # offers no request form; a caller reaching this endpoint directly is
    # told why instead of being fed the usual answer. Password reset is
    # refused on a demo for the same kind of reason.
    if settings.INVENTARI_DEMO:
        raise catalogue_refusal('demo_registration_locked')

    already_known = await AuthService.email_exists_async(
        db, request_in.email
    ) or await AuthService.has_registration_request_async(db, request_in.email)

    if not already_known:
        await AuthService.create_registration_request_async(db, request_in)

    return RegistrationRequestResponse(message='Request submitted successfully')


@router.get(
    '/registration-requests',
    response_model=PaginatedResponse[RegistrationRequestSchema],
)
async def list_registration_requests(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _current_user=Depends(get_superuser),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """List all pending registration requests (admin only)."""
    requests = await AuthService.get_pending_requests_async(db)
    return PaginatedResponse.from_full_list(requests, offset=offset, limit=limit)


@router.post(
    '/registration-requests/{request_id}/approve',
    response_model=RegistrationApproveResponse,
)
async def approve_registration_request(
    request_id: str,
    current_user=Depends(get_superuser),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    lang: Language = Depends(get_current_lang),
):
    """Approve a registration request and generate a token (admin only)."""
    req = await AuthService.get_request_by_id_async(db, request_id)
    if not req:
        raise NotFoundException('request', lang)

    token = await AuthService.approve_registration_request_async(
        db, req, current_user.id
    )

    from app.services.email_service import email_service
    from app.services.notification_service import notification_service

    admin_notifications = await notification_service.notify_superusers_async(
        db,
        title=get_error_message('reg_request_approved_title', lang),
        content=get_error_message(
            'reg_request_approved_content',
            lang,
            email=req.email,
            admin=current_user.email,
        ),
        type='success',
        link='/settings',
        exclude_user_id=current_user.id,
    )
    from app.core.public_api import core_api

    await core_api.notifications.publish_async(
        db,
        [notification_service.to_dto(n) for n in admin_notifications],
    )

    # Last: the mail queue commits on its own, and nothing after it may fail
    # and take back the approval the link in the mail stands for.
    smtp_config = await AuthService.get_org_smtp_config_async(
        db, current_user.organization_id
    )
    registration_link = f'/register?token={token}'
    # The link goes by mail only where there is a mail server to take it. The
    # queue accepts a row either way and fails it after its retries, so asking
    # it would answer "sent" on an installation that never sends: the screen
    # would say the mail left and the one copy of the token would be gone.
    # Without SMTP the response says so and the administrator hands the link
    # over (the invitation path does the same).
    email_sent = False
    if email_service.is_configured(smtp_config):
        full_link = f'{settings.FRONTEND_URL.rstrip("/")}{registration_link}'
        email_sent = await email_service.send_registration_link_async(
            req.email,
            registration_link,
            lang=req.preferred_language,
            smtp_config=smtp_config,
            organization_id=current_user.organization_id,
            # A delivery that fails later in the queue must still reach the
            # administrator who approved, with the link in hand.
            failure_notice={
                'user_id': str(current_user.id),
                'title': get_error_message('reg_link_undelivered_title', lang),
                'content': get_error_message(
                    'reg_link_undelivered_content',
                    lang,
                    email=req.email,
                    link=full_link,
                ),
                'link': '/settings',
            },
        )

    return {
        'message': 'Request approved',
        'registration_token': token,
        'registration_link': registration_link,
        'email_sent': email_sent,
    }


@router.post(
    '/registration-requests/{request_id}/reject',
    response_model=RegistrationRequestResponse,
)
async def reject_registration_request(
    request_id: str,
    current_user=Depends(get_superuser),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    lang: Language = Depends(get_current_lang),
):
    """Reject a registration request (admin only)."""
    req = await AuthService.get_request_by_id_async(db, request_id)
    if not req:
        raise NotFoundException('request', lang)

    await AuthService.reject_registration_request_async(db, req)

    from app.services.notification_service import notification_service

    admin_notifications = await notification_service.notify_superusers_async(
        db,
        title=get_error_message('reg_request_rejected_title', lang),
        content=get_error_message(
            'reg_request_rejected_content',
            lang,
            email=req.email,
            admin=current_user.email,
        ),
        type='error',
        link='/settings',
        exclude_user_id=current_user.id,
    )
    from app.core.public_api import core_api

    await core_api.notifications.publish_async(
        db,
        [notification_service.to_dto(n) for n in admin_notifications],
    )

    return RegistrationRequestResponse(message='Request rejected')


class RegistrationLinkInfo(BaseModel):
    email: str
    full_name: str | None = None


@router.get('/registration-link/{token}', response_model=RegistrationLinkInfo)
@limiter.limit('30/minute')
async def registration_link_info(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Whose account an approval link finishes, so the form can show it.

    The caller holds the link the administrator handed them: the address and
    name they gave in the request go back to them. An unknown or spent token
    is the same bare 404 the invitation check gives.
    """
    req = await AuthService.get_request_by_token_async(db, token)
    if not req:
        raise NotFoundException('request', get_current_lang())
    return RegistrationLinkInfo(email=req.email, full_name=req.full_name)


@router.post('/register-complete', response_model=UserSchema)
async def register_complete(
    user_in: RegistrationComplete,
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Complete registration using a token."""
    req = await AuthService.get_request_by_token_async(db, user_in.token)
    if not req:
        raise catalogue_refusal('token_invalid', lang=user_in.preferred_language)

    if await AuthService.email_exists_async(db, req.email):
        raise ConflictException(
            code='EMAIL_ALREADY_EXISTS',
            message=get_error_message(
                'user_already_exists',
                user_in.preferred_language or get_current_lang(),
            ),
        )

    from app.schemas.user import UserCreate as UserCreateSchema

    user_in_ext = UserCreateSchema(
        email=req.email,
        password=user_in.password,
        full_name=user_in.full_name or req.full_name,
        # The completion form's explicit choice wins; otherwise the request's
        # captured language carries over, and failing that the language this
        # request arrived in — never a hardcoded 'en'.
        preferred_language=(
            user_in.preferred_language or req.preferred_language or get_current_lang()
        ),
    )

    return await AuthService.register_user_async(
        db, user_in_ext, registration_request=req
    )
