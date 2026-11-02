"""GDPR data-subject erasure: in-place user anonymization.

The user row is kept (audit FKs from ItemHistory/AuditLog stay intact) but
all personal data is destroyed: email, full name, password. The account is
deactivated, which immediately rejects both JWT and API-key auth
(``identity_service`` checks ``is_active`` on every request), and the
token family is revoked via the blacklist as defense in depth.
RegistrationRequest rows (pre-signup email/name) and the invitations
issued for that address are anonymized too.

Rows with audit value (ItemHistory, AuditLog, StockMove.created_by, ...)
keep pointing at the anonymized user — the identifier is a UUID, not
personal data. Audit entries go further: they are immutable in the
database (``audit_log_immutable`` refuses UPDATE and DELETE), and a
member or invitation entry carries the address as its name. Erasure
therefore rewrites what is mutable and states what it leaves — never a
write behind the trigger. See docs/GDPR_MANUAL_PROCEDURE.md for the
manual flow and for the records that keep the address afterwards.
"""

import secrets
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger
from app.core.token_blacklist import token_blacklist
from app.models.organization import OrganizationInvitation
from app.models.user import RegistrationRequest, User

logger = get_logger(__name__)

ANONYMIZED_EMAIL_DOMAIN = 'anonymized.invalid'


async def anonymize_user_async(db: AsyncSession, user_id: UUID) -> User:
    """Destroy the personal data of *user_id*.

    Raises ValueError when the user does not exist. The caller owns the
    transaction (commit/rollback).
    """
    user = await db.get(User, user_id)
    if user is None:
        raise ServiceRejectionError('user_not_found')

    old_email = user.email

    user.email = f'deleted-{user_id.hex}@{ANONYMIZED_EMAIL_DOMAIN}'
    user.full_name = 'Deleted User'
    user.hashed_password = secrets.token_hex(32)
    user.is_active = False

    # Pre-signup registration requests carry the raw email and full name.
    requests = await db.scalars(
        select(RegistrationRequest).where(RegistrationRequest.email == old_email)
    )
    for request in requests:
        request.email = user.email
        request.full_name = None
        request.token = None

    # An invitation names the address its code was issued for, so it is
    # personal data of the same person. This row is an ordinary
    # organization record — the journal holds the record of who was
    # invited — so it is rewritten in place like the account itself. The
    # address becomes the one no account can hold, which keeps the code
    # bound to an address: clearing the binding instead would leave a
    # live code that opens for whoever holds the link.
    invitations = await db.scalars(
        select(OrganizationInvitation).where(
            func.lower(OrganizationInvitation.invited_email) == old_email.lower()
        )
    )
    for invitation in invitations:
        invitation.invited_email = user.email

    await db.flush()

    await token_blacklist.revoke_user_family(str(user_id))
    logger.info('[GDPR] Anonymized user %s', user_id)
    return user
