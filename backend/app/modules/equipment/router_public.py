"""Public attestation router — zero-login token-based confirm/dispute flow.

These endpoints are intentionally unauthenticated: each unique token
grants access to exactly one assignment response.
"""

from typing import Any, NoReturn

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_async_db
from app.core.exceptions import catalogue_status_refusal
from app.core.limiter import limiter
from app.core.logging import get_logger
from app.i18n import Language
from app.i18n.service import get_current_lang

from .attestation_service import (
    confirm_response,
    dispute_response,
    get_public_response,
)
from .schemas import AuditResponseSchema, DisputeForm

logger = get_logger(__name__)

router_public = APIRouter(
    prefix='/public/attestation', tags=['Asset Attestation (Public)']
)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.client.host if request.client else None


# Every refusal the response service raises is a reason token from its closed
# vocabulary. This table is that whole vocabulary, each token with its
# catalogue key; ``_refuse`` answers anything else through the catalogue as
# well, so a token added in the service one day can never reach the public
# page raw.
_REFUSALS: dict[str, str] = {
    'not_found': 'attestation_not_found',
    'expired': 'attestation_expired',
    'assignment_already_returned': 'assignment_already_returned',
    'campaign_closed': 'campaign_closed',
    'assignment_required': 'attestation_assignment_required',
    'assignment_not_found': 'attestation_not_found',
}
# The status of each token that is not a plain 400. A table of its own
# rather than (status, key) pairs, so the error-code page can read every key
# this door answers with straight from the table above.
_STATUSES: dict[str, int] = {
    'not_found': 404,
    'expired': 410,
    'assignment_already_returned': 409,
    'campaign_closed': 409,
}


def _refuse(exc: ValueError, lang: Language) -> NoReturn:
    """Turn a service reason into an HTTP refusal that speaks the catalogue.

    An unmapped reason is a bug in the service vocabulary, not a message to
    hand the reader: it is logged whole and answered with a named refusal.
    """
    reason = str(exc)
    key = _REFUSALS.get(reason)
    if key is None:
        logger.warning('Unmapped attestation refusal: %r', reason)
        key = 'attestation_refused'
    raise catalogue_status_refusal(key, _STATUSES.get(reason, 400), lang=lang) from exc


@router_public.get('/{token}', response_model=AuditResponseSchema)
@limiter.limit('30/minute')
async def get_attestation(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    response = await get_public_response(db, token)
    if not response:
        raise catalogue_status_refusal('attestation_not_found', 404)
    return response


@router_public.post('/{token}/confirm', response_model=AuditResponseSchema)
@limiter.limit('10/minute')
async def confirm_attestation(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    lang = get_current_lang()
    ip = _client_ip(request)
    ua = request.headers.get('User-Agent', '')[:500]
    try:
        await confirm_response(db, token, ip=ip, user_agent=ua)
    except ValueError as exc:
        _refuse(exc, lang)
    return await get_public_response(db, token)


@router_public.post('/{token}/dispute', response_model=AuditResponseSchema)
@limiter.limit('10/minute')
async def dispute_attestation(
    token: str,
    data: DisputeForm,
    request: Request,
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    lang = get_current_lang()
    ip = _client_ip(request)
    ua = request.headers.get('User-Agent', '')[:500]
    try:
        await dispute_response(
            db,
            token,
            dispute_type=data.dispute_type,
            reason=data.reason,
            ip=ip,
            user_agent=ua,
            assignment_id=data.assignment_id,
        )
    except ValueError as exc:
        _refuse(exc, lang)
    return await get_public_response(db, token)
