"""Public invitation router — zero-login validity check for a join link.

Unauthenticated on purpose: the caller is the person the invitation was
emailed to, arriving before they have an account. The endpoint answers one
question — does this code still open a door — so the /join page can say
"invalid or expired" on the screen instead of silently dropping the visitor
on /login, where registering means an organization of their own.
"""

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_async_db
from app.core.exceptions import AppException, rejection_code
from app.core.limiter import limiter
from app.i18n.service import get_current_lang, get_error_message
from app.services._org_membership import invitation_preview, open_invitation


class InvitationCheckResponse(BaseModel):
    valid: bool
    #: What the visitor needs to see before creating an account: which
    #: organization, who invited them, in what role, and the address the
    #: invitation is for (None on an older bearer code).
    organization_name: str | None = None
    inviter_name: str | None = None
    role: str | None = None
    invited_email: str | None = None


router_public = APIRouter(prefix='/public/invitation', tags=['Invitations (Public)'])


@router_public.get('/{code}', response_model=InvitationCheckResponse)
@limiter.limit('30/minute')
async def check_invitation(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Whether a join link still works for its code.

    The refusal is a bare 404: it must not separate "unknown code" from
    "expired yesterday" — both tell the visitor the same thing, ask for a
    fresh link — and it must not say whether a code ever existed, which a
    probe could otherwise use to sweep the code space.
    """
    invitation = await open_invitation(db, code)
    if invitation is None:
        # The code is the one registering with a dead code answers (a stable
        # contract); the sentence is not: this check never sees an address, so
        # the registration advice of that key would be wrong here.
        lang = get_current_lang()
        raise AppException(
            status_code=404,
            code=rejection_code('organization_invite_invalid'),
            message=get_error_message('organization_invite_link_dead', lang),
            extra={'lang': lang},
        )
    preview = await invitation_preview(db, invitation)
    return InvitationCheckResponse(
        valid=True,
        organization_name=preview.organization_name,
        inviter_name=preview.inviter_name,
        role=preview.role,
        invited_email=invitation.invited_email,
    )
