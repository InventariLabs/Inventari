from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import get_async_db
from app.core.exceptions import NotFoundException, catalogue_refusal
from app.core.limiter import limiter
from app.i18n.service import get_current_lang
from app.schemas.auth import PasswordResetRequestOut
from app.schemas.user import validate_password_byte_ceiling
from app.services.auth_service import AuthService, refuse_credential_change_in_demo
from app.services.email_service import EmailService

router = APIRouter()


class PasswordResetRequestIn(BaseModel):
    """Body for ``POST /auth/password-reset/request``."""

    email: EmailStr


class PasswordResetCheckIn(BaseModel):
    """Body for ``POST /auth/password-reset/check``."""

    token: str


class PasswordResetConfirmIn(BaseModel):
    """Body for ``POST /auth/password-reset/confirm``."""

    token: str
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator('new_password')
    @classmethod
    def password_byte_ceiling(cls, v: str) -> str:
        return validate_password_byte_ceiling(v)


@router.post(
    '/password-reset/request',
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PasswordResetRequestOut,
)
@limiter.limit('3/hour')
async def request_password_reset(
    request: Request,
    data: PasswordResetRequestIn,
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> PasswordResetRequestOut:
    """Accept a password-reset request. Always returns 202 to avoid leaking
    whether the email matches an existing user.
    """
    refuse_credential_change_in_demo()
    result = await AuthService.request_password_reset_async(db, data.email)
    if result is not None:
        token, lang, organization_id = result
        reset_link = f'/reset-password/{token}'
        # The mail server the user's organization set up in Settings. Without
        # it the queued job fell back to the installation's own settings, found
        # them empty and failed "SMTP is not configured" on an install that
        # sends every other mail.
        smtp_config = await AuthService.get_org_smtp_config_async(db, organization_id)
        await EmailService.send_password_reset_email_async(
            data.email,
            reset_link,
            lang=lang,
            smtp_config=smtp_config,
            organization_id=organization_id,
        )
    return PasswordResetRequestOut(
        status='accepted',
        email_delivery_configured=await AuthService.mail_delivery_available_async(db),
    )


@router.post('/password-reset/check', status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit('30/minute')
async def check_password_reset_token(
    request: Request,
    data: PasswordResetCheckIn,
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    """Say whether a reset link can still be used, without using it.

    The reset page asks this on arrival; a link from an old e-mail is the
    usual way to land there with a token that is spent or expired.
    """
    try:
        await AuthService.check_password_reset_token_async(db, data.token)
    except ValueError as exc:
        raise catalogue_refusal('invalid_reset_token') from exc


@router.post('/password-reset/confirm')
@limiter.limit('5/hour')
async def confirm_password_reset(
    request: Request,
    data: PasswordResetConfirmIn,
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Verify a reset token and replace the user's password."""
    try:
        await AuthService.confirm_password_reset_async(
            db, data.token, data.new_password
        )
    except ValueError as exc:
        raise catalogue_refusal('invalid_reset_token') from exc
    return {'status': 'success'}


# ── TESTING-only helper ───────────────────────────────────────────────────
# Exposes a fresh reset token for a given email so that Playwright tests
# (which cannot read the dev SMTP transport) can drive the
# ``/reset-password/:token`` UI flow end-to-end. Guarded by TESTING so it
# can never be reached in a production deployment.
if settings.TESTING:

    class DevTokenIn(BaseModel):
        email: EmailStr

    @router.post('/password-reset/_dev_token', include_in_schema=False)
    async def dev_issue_token(
        data: DevTokenIn,
        db: AsyncSession = Depends(get_async_db, scope='function'),
    ):
        result = await AuthService.request_password_reset_async(db, data.email)
        if result is None:
            raise NotFoundException('user', get_current_lang())
        token, _lang, _organization_id = result
        return {'token': token}
