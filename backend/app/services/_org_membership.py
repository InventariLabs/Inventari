import secrets
from datetime import UTC, datetime, timedelta
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.events import SystemEvent, TenantEventPayload, event_bus
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    ServiceRejectionError,
    catalogue_refusal,
)
from app.core.logging import get_logger
from app.i18n.service import get_current_lang, get_error_message
from app.models.organization import Organization, OrganizationInvitation
from app.models.user import User
from app.services.audit_service import log_action_async

logger = get_logger(__name__)


async def _drop_org_role_links(
    db: AsyncSession, user_id: UUID, organization_id: UUID
) -> None:
    """Forget the roles *user_id* held in *organization_id*.

    ``UserRole`` carries no organization, so a membership change used to
    leave the old links in place — a user with a role in organization A who
    joined B kept the A grants, and rejoining A silently restored them.
    Only links to roles owned by the organization being left are removed —
    which, now that every role has an organization, is all of the user's.
    """
    from app.models.role import Role, UserRole

    stale = await db.scalars(
        select(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id, Role.organization_id == organization_id)
    )
    dropped = 0
    for link in stale.all():
        await db.delete(link)
        dropped += 1
    if dropped:
        logger.info(
            'Dropped %d role link(s) for user %s leaving organization %s',
            dropped,
            user_id,
            organization_id,
        )


# Crockford-style base32: no 0/O or 1/I, so a code read out loud or copied off
# a screen cannot land on the wrong character. 32^8 ≈ 1.1e12 codes against a
# rate limit of 10 attempts per hour per account puts guessing out of reach for
# the whole life of a code, which 10^6 six-digit codes were not.
INVITE_CODE_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'
INVITE_CODE_LENGTH = 8

# A day is too short for a warehouse — an invitation sent on Friday has to
# survive the weekend, and a clerk on another shift does not read mail daily.
# A month is an access grant left lying around. Seven days is where the
# identity vendors sit, and what makes the link worth binding to an address.
INVITE_TTL = timedelta(days=7)


def _gen_invite_code(length: int = INVITE_CODE_LENGTH) -> str:
    return ''.join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(length))


async def open_invitation(db: AsyncSession, code: str) -> OrganizationInvitation | None:
    """The invitation *code* would still open a door for: unspent, unwithdrawn, unexpired.

    The public /join page asks this before it sends a signed-out visitor
    anywhere: a dead link has to say so on the screen instead of handing the
    visitor a registration form that only refuses at submit — or worse, a
    silent redirect to /login. The same three conditions joining enforces,
    minus the address binding, which stays a registration-time check.
    """
    return await db.scalar(
        select(OrganizationInvitation).where(
            OrganizationInvitation.code == code,
            OrganizationInvitation.expires_at > datetime.now(UTC),
            OrganizationInvitation.is_used == False,
            OrganizationInvitation.revoked_at.is_(None),
        )
    )


class InvitationPreview(NamedTuple):
    organization_name: str | None
    inviter_name: str | None
    role: str | None


async def invitation_preview(
    db: AsyncSession, invitation: OrganizationInvitation
) -> InvitationPreview:
    """What a live invitation tells the person it was sent to: where, from whom, as what."""
    from app.models.role import Role

    organization_name = await db.scalar(
        select(Organization.name).where(Organization.id == invitation.organization_id)
    )
    inviter = await db.get(User, invitation.created_by)
    role: str | None = invitation.role
    if invitation.role_id:
        role = await db.scalar(select(Role.name).where(Role.id == invitation.role_id))
    return InvitationPreview(
        organization_name,
        (inviter.full_name or inviter.email) if inviter else None,
        role,
    )


async def create_invitation_code(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    role: str = 'user',
    role_id: UUID | None = None,
    invited_email: str | None = None,
) -> dict:
    """Mint one invitation, for one address.

    Every call issues a new code. An earlier version handed back a live code
    for the same ``(role, role_id)`` pair instead, which was a harmless saving
    while a code was a bearer token: now that it names a recipient, returning
    it to a second caller would send one person the invitation meant for
    another, bound to that other person's address.
    """
    role_label = role
    if role_id is not None:
        from app.models.role import Role

        custom_role = await db.get(Role, role_id)
        if custom_role is None or custom_role.organization_id != organization_id:
            raise ServiceRejectionError('role_not_in_organization')
        # The name the organization chose for the role. Carried out of here so
        # the invitation email can say what the invitee is being made without
        # loading the role a second time.
        role_label = custom_role.name

    now = datetime.now(UTC)
    code = _gen_invite_code()
    while await db.scalar(
        select(OrganizationInvitation).where(OrganizationInvitation.code == code)
    ):
        code = _gen_invite_code()

    invitation = OrganizationInvitation(
        organization_id=organization_id,
        code=code,
        created_by=user_id,
        expires_at=now + INVITE_TTL,
        role=role,
        role_id=role_id,
        invited_email=invited_email,
    )
    db.add(invitation)
    await db.flush()
    return {
        # Not in the public response: the entry in the log points at this row,
        # where it used to point at the organization.
        'id': invitation.id,
        'code': code,
        'expires_at': invitation.expires_at.isoformat(),
        'role': role,
        'role_id': str(role_id) if role_id else None,
        'role_label': role_label,
        'invited_email': invited_email,
    }


# How long a dead invitation stays worth looking at. Beyond that it is neither
# actionable nor evidence — the audit log keeps the record of who was invited.
INVITE_RETENTION = timedelta(days=90)


async def _delivery_by_address(
    db: AsyncSession,
    organization_id: UUID,
    invitations: list[OrganizationInvitation],
) -> dict[str, tuple[datetime, str]]:
    """The newest queued mail per invited address: when it was written, and how it ended.

    Correlated by address rather than by an identifier, because an
    invitation and its mail share no key — the queue takes a recipient, a
    subject and a body, and knows nothing of what prompted them. Within one
    organization the address is enough: a code opens only for the address it
    was issued for, and a resend writes a newer row for the same one, which
    is the state worth showing. The case it cannot separate is two live
    invitations to the same person, and those two rows then report the same
    last attempt — which is the truth about that mailbox, if not about each
    code.
    """
    from app.models.email_job import EmailJob

    addresses = {inv.invited_email for inv in invitations if inv.invited_email}
    if not addresses:
        return {}

    rows = await db.execute(
        select(EmailJob.to_email, EmailJob.created_at, EmailJob.status)
        .where(
            EmailJob.organization_id == organization_id,
            EmailJob.to_email.in_(addresses),
        )
        .order_by(EmailJob.created_at.desc())
    )
    newest: dict[str, tuple[datetime, str]] = {}
    for to_email, created_at, status in rows:
        newest.setdefault(to_email, (created_at, status))
    return newest


def _delivery_of(
    invitation: OrganizationInvitation, newest: dict[str, tuple[datetime, str]]
) -> str | None:
    """How the mail for this invitation ended, or None when there is none to read.

    None covers three real cases the screen must not confuse with a
    failure: a bearer code minted for nobody in particular, an installation
    with no SMTP at all where the administrator passes the link on by hand,
    and a row queued before the queue recorded its tenant.
    """
    if not invitation.invited_email:
        return None
    entry = newest.get(invitation.invited_email)
    if entry is None:
        return None
    created_at, status = entry
    # Mail that predates the invitation was sent for an earlier one; this
    # invitation's own attempt is simply not in the queue any more.
    return status if created_at >= invitation.created_at else None


async def list_invitations(
    db: AsyncSession, organization_id: UUID, limit: int = 20
) -> list[dict]:
    """Invitations issued for this organization, newest first.

    The screen had none of this: the only way to learn whether anyone had used
    a generated link was that they turned up in the member list — or did not,
    in which case the sole move was to generate another.

    Each row also carries how its mail ended. An invitation whose message
    exhausted the queue's retries is indistinguishable, on a list that only
    knows "not used yet", from one sitting unread in an inbox — and the two
    ask for opposite things from an administrator: send it another way, or
    wait.

    Reading the list also clears out invitations that died more than ninety
    days ago. Nothing ever removed one, so the list grew for the life of the
    installation — sixteen rows, thirteen of them corpses, was what the
    settings screen had become.
    """
    await db.execute(
        delete(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.expires_at < datetime.now(UTC) - INVITE_RETENTION,
        )
    )

    result = await db.execute(
        select(OrganizationInvitation)
        .where(
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.revoked_at.is_(None),
        )
        .order_by(OrganizationInvitation.created_at.desc())
        .limit(limit)
    )
    invitations = list(result.scalars().all())
    newest = await _delivery_by_address(db, organization_id, invitations)
    return [
        {
            'id': inv.id,
            'code': inv.code,
            'role': inv.role,
            'role_id': inv.role_id,
            'is_used': inv.is_used,
            'expires_at': inv.expires_at,
            'created_at': inv.created_at,
            'invited_email': inv.invited_email,
            'used_by_user_id': inv.used_by_user_id,
            'used_at': inv.used_at,
            'email_status': _delivery_of(inv, newest),
        }
        for inv in invitations
    ]


async def resend_invitation(
    db: AsyncSession,
    organization_id: UUID,
    invitation_id: UUID,
    *,
    actor_user_id: UUID | None = None,
) -> dict:
    """Give a pending invitation another seven days, unchanged otherwise.

    The code stays the same, so a recipient who still has the first mail is
    not left holding a dead link. Seven days is only enough because this
    exists: without it an invitation that timed out would have to be invented
    from scratch, which is how the previous fifteen-minute window was survived
    at all.

    The extension is journalled in the caller's transaction, so the entry
    and the new deadline stand or fall together.

    Raises ValueError when the invitation belongs to another organization,
    does not exist, was withdrawn, has already been redeemed, or names no
    address to send it to.
    """
    invitation = await db.scalar(
        select(OrganizationInvitation)
        .where(
            OrganizationInvitation.id == invitation_id,
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.revoked_at.is_(None),
            OrganizationInvitation.is_used == False,
        )
        .with_for_update()
    )
    if invitation is None or not invitation.invited_email:
        raise ServiceRejectionError('invitation_not_found')

    old_expires_at = invitation.expires_at
    invitation.expires_at = datetime.now(UTC) + INVITE_TTL

    role_label = invitation.role
    if invitation.role_id is not None:
        from app.models.role import Role

        custom_role = await db.get(Role, invitation.role_id)
        if custom_role is not None:
            role_label = custom_role.name

    # Extending a live way into the organization is an access act; the code
    # itself never goes in — an entry a reader can join with is not an entry.
    await log_action_async(
        db,
        organization_id=organization_id,
        user_id=actor_user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.INVITATION,
        target_id=invitation.id,
        snapshot={
            'invited_email': invitation.invited_email,
            'role': invitation.role,
            'before': {'expires_at': old_expires_at.isoformat()},
            'after': {'expires_at': invitation.expires_at.isoformat()},
        },
    )
    await db.flush()
    logger.info(
        'Invitation %s resent in organization %s', invitation_id, organization_id
    )
    return {
        'code': invitation.code,
        'expires_at': invitation.expires_at.isoformat(),
        'role': invitation.role,
        'role_id': str(invitation.role_id) if invitation.role_id else None,
        'role_label': role_label,
        'invited_email': invitation.invited_email,
    }


async def revoke_invitation(
    db: AsyncSession, organization_id: UUID, invitation_id: UUID
) -> OrganizationInvitation:
    """Withdraw an invitation that has not been redeemed yet.

    Marks the row rather than deleting it, so the record of who was invited
    survives the withdrawal. Returns the invitation so the caller can record
    what was withdrawn — it leaves the list, and the audit entry is then the
    only place it is named.

    Raises ValueError when the invitation belongs to another organization,
    does not exist, or has already been redeemed: taking back a code somebody
    has already walked through would say the membership can be undone here,
    and it cannot.
    """
    invitation = await db.scalar(
        select(OrganizationInvitation)
        .where(
            OrganizationInvitation.id == invitation_id,
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.revoked_at.is_(None),
            OrganizationInvitation.is_used == False,
        )
        .with_for_update()
    )
    if invitation is None:
        raise ServiceRejectionError('invitation_not_found')

    invitation.revoked_at = datetime.now(UTC)
    await db.flush()
    logger.info(
        'Invitation %s revoked in organization %s', invitation_id, organization_id
    )
    return invitation


async def _announce_membership_change(
    db: AsyncSession, user: User, joined: UUID, left: UUID | None
) -> None:
    """Record the join (and the departure it implies) in the outbox.

    Announced with the join, not after it: the outbox row commits, or rolls
    back, with the membership it describes. The payload names the person
    rather than carrying the row, which holds the password hash.
    """
    member = {
        'id': str(user.id),
        'email': user.email,
        'full_name': user.full_name,
        'role': user.role,
    }
    if left is not None:
        await event_bus.emit_transactional(
            db,
            SystemEvent.USER_LEFT_ORG,
            TenantEventPayload.model_validate(
                {'organization_id': str(left), 'user': member}
            ),
        )
    await event_bus.emit_transactional(
        db,
        SystemEvent.USER_JOINED_ORG,
        TenantEventPayload.model_validate(
            {'organization_id': str(joined), 'user': member}
        ),
    )


async def join_organization(db: AsyncSession, code: str, user_id: UUID) -> Organization:
    now = datetime.now(UTC)
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise ServiceRejectionError('user_not_found')

    # Locked, because the check and the write are far apart: everything
    # between here and `is_used = True` runs while the row is still unspent.
    # Two requests carrying the same code and arriving together both read it
    # as free, and the second one's write only set a flag that was already
    # set -- a code meant to admit one person admitted both. The second read
    # now waits, and when it returns the row no longer matches the filter.
    invitation = await db.scalar(
        select(OrganizationInvitation)
        .where(
            OrganizationInvitation.code == code,
            OrganizationInvitation.expires_at > now,
            OrganizationInvitation.is_used == False,
            OrganizationInvitation.revoked_at.is_(None),
        )
        .with_for_update()
    )

    if not invitation:
        raise ServiceRejectionError('invitation_code_invalid')

    # The code opens for one address only. A link that spends a week in the
    # wrong mailbox, a shared account or a forwarded thread is then worth
    # nothing. The refusal says that the link is for another address — the
    # person holding a live code and signed in as someone else needs that to
    # know they should sign out — and never names the address the invitation
    # was for, which would tell a stranger who was invited.
    #
    # Codes minted before invitations carried an address have none, and keep
    # the bearer behaviour until they expire on their own.
    if invitation.invited_email and (
        invitation.invited_email.casefold() != user.email.casefold()
    ):
        logger.info(
            'Invitation %s refused: issued for another address',
            invitation.id,
        )
        raise ServiceRejectionError('invitation_other_address')

    # Already one of them. The invitation names the role of an arrival, and
    # nobody arrives here: writing it over the member's own role would let
    # the link demote whoever opens it. An administrator minting a
    # `role=user` code for their own organization and following it came out
    # of this function a plain user — past the sole-administrator guard,
    # which only ever runs when the organization changes.
    #
    # So nothing is written and nothing is spent. The code has admitted
    # nobody, and burning it on a member who was already in would leave the
    # invitation the person still to arrive is carrying dead.
    if user.organization_id == invitation.organization_id:
        organization = await db.scalar(
            select(Organization).where(Organization.id == invitation.organization_id)
        )
        if organization is None:
            raise ServiceRejectionError('organization_not_found')
        return organization

    old_organization_id = user.organization_id
    if old_organization_id and old_organization_id != invitation.organization_id:
        current_org = await db.scalar(
            select(Organization).where(Organization.id == old_organization_id)
        )
        if current_org and current_org.created_by == user.id:
            other_admins = await db.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.organization_id == old_organization_id,
                    User.id != user.id,
                    User.role == 'admin',
                )
            )
            if other_admins == 0:
                members_count = await db.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.organization_id == old_organization_id)
                )
                if (members_count or 0) > 1:
                    raise ConflictException(
                        code='SOLE_ADMINISTRATOR',
                        message=get_error_message(
                            'sole_administrator_cannot_leave', get_current_lang()
                        ),
                    )

    old_role = user.role
    switching = bool(
        old_organization_id and old_organization_id != invitation.organization_id
    )
    if switching:
        assert old_organization_id is not None  # implied by `switching`
        await _drop_org_role_links(db, user.id, old_organization_id)
        # The door that just closed. Membership is access, so both ends of a
        # switch are recorded; both entries ride the caller's commit.
        await log_action_async(
            db,
            organization_id=old_organization_id,
            user_id=user.id,
            action=AuditAction.SOFT_DELETE,
            target_type=AuditTargetType.ORG_MEMBER,
            target_id=user.id,
            snapshot={
                'name': user.email,
                'before': {'organization': True, 'role': old_role},
                'after': {'organization': False},
            },
        )

    user.organization_id = invitation.organization_id
    # The role the inviter chose, not a constant: an admin inviting a manager
    # used to have to wait for them to arrive and then promote them by hand.
    user.role = invitation.role or 'user'

    # Mark the invitation as consumed so the code cannot be reused by
    # another user within its validity window. The lookup above already
    # filters is_used == False, so without this line a single code could admit
    # unlimited users until natural expiry.
    invitation.is_used = True
    # Who walked through the door, and when. `is_used` said only that someone
    # had, which left the list unable to name them.
    invitation.used_by_user_id = user.id
    invitation.used_at = now

    # The door that just opened.
    await log_action_async(
        db,
        organization_id=invitation.organization_id,
        user_id=user.id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.ORG_MEMBER,
        target_id=user.id,
        snapshot={'name': user.email, 'role': user.role},
    )

    await _announce_membership_change(
        db, user, invitation.organization_id, old_organization_id if switching else None
    )
    await db.flush()

    if invitation.role_id:
        # The custom role the inviter picked goes on top of the enum base
        # level. If the role vanished meanwhile (SET NULL keeps the column
        # clean, but a flush race is still possible), the member keeps the
        # enum level rather than losing the join.
        from app.services.permissions_service import assign_role_async

        try:
            await assign_role_async(
                db,
                organization_id=invitation.organization_id,
                user_id=user.id,
                role_id=invitation.role_id,
                actor_user_id=invitation.created_by,
            )
        except ValueError:
            logger.warning(
                'Invitation %s names role %s that no longer fits organization %s — joined with enum level only',
                invitation.code,
                invitation.role_id,
                invitation.organization_id,
            )

    organization = await db.scalar(
        select(Organization).where(Organization.id == invitation.organization_id)
    )
    if organization is None:
        raise ServiceRejectionError('organization_not_found')

    return organization


async def leave_organization(
    db: AsyncSession, user_id: UUID, organization_id: UUID
) -> None:
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise ServiceRejectionError('user_not_found')

    org = await db.scalar(
        select(Organization).where(Organization.id == organization_id)
    )
    if org and org.created_by == user.id:
        other_admins = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.organization_id == organization_id,
                User.id != user.id,
                User.role == 'admin',
            )
        )
        if other_admins == 0:
            raise ConflictException(
                code='SOLE_ADMINISTRATOR',
                message=get_error_message(
                    'sole_administrator_cannot_leave', get_current_lang()
                ),
            )

    old_role = user.role
    await _drop_org_role_links(db, user.id, organization_id)
    user.organization_id = None
    user.role = 'user'
    # Leaving ends a grant of access, whether the member or an administrator
    # brought it about; the entry mirrors the removal one and rides the same
    # transaction as the membership end.
    await log_action_async(
        db,
        organization_id=organization_id,
        user_id=user.id,
        action=AuditAction.SOFT_DELETE,
        target_type=AuditTargetType.ORG_MEMBER,
        target_id=user.id,
        snapshot={
            'name': user.email,
            'before': {'organization': True, 'role': old_role},
            'after': {'organization': False},
        },
    )
    await db.flush()


async def remove_member(db: AsyncSession, user_to_remove: User) -> None:
    if user_to_remove.organization_id is not None:
        await _drop_org_role_links(
            db, user_to_remove.id, user_to_remove.organization_id
        )
    user_to_remove.organization_id = None
    user_to_remove.role = 'user'
    await db.flush()


async def change_member_role(
    db: AsyncSession,
    member: User,
    role: str | None,
    organization_id: UUID,
    *,
    role_id: UUID | None = None,
    actor_user_id: UUID | None = None,
) -> None:
    """Give *member* a different role inside *organization_id*.

    Exactly one of *role* (a built-in level) or *role_id* (an org-scoped
    custom role) is required. Picking a built-in level also drops the member's
    custom-role links; picking a custom role replaces whichever one the member
    held — one custom role per person. A custom role assigned to an
    administrator also takes the enum level down to ``user``: ``has_permission``
    short-circuits on ``admin`` without ever looking at the role's permission
    set, so keeping the level would make the assignment a label change only.

    Refuses to take away the organization's last administrator: a workspace
    whose every admin has been demoted can no longer manage modules, members
    or approvals, and nothing short of database access gets it back. The guard
    covers the custom-role path too — a custom role replaces the enum fallback
    in permission resolution, so moving the last admin onto one could strip
    ``admin:access`` just the same.
    """
    if (role is None) == (role_id is None):
        raise ServiceRejectionError('member_role_exactly_one')

    if member.role == 'admin' and role != 'admin':
        other_admins = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.organization_id == organization_id,
                User.id != member.id,
                User.role == 'admin',
            )
        )
        if not other_admins:
            raise ConflictException(
                code='SOLE_ADMINISTRATOR',
                message=get_error_message(
                    'sole_administrator_role_locked', get_current_lang()
                ),
            )

    if role is not None:
        member.role = role
        await _drop_org_role_links(db, member.id, organization_id)
    else:
        from app.services.permissions_service import assign_role_async

        assert role_id is not None  # guaranteed by the exactly-one check above
        # One custom role per person: forget the previous links first.
        await _drop_org_role_links(db, member.id, organization_id)
        await assign_role_async(
            db,
            organization_id=organization_id,
            user_id=member.id,
            role_id=role_id,
            actor_user_id=actor_user_id or member.id,
        )
        # The role now governs, so the level must stop bypassing it — an
        # 'admin' enum level would keep short-circuiting every permission
        # check. The last-administrator guard above has already vetted the
        # demotion, so this cannot strand the workspace.
        if member.role == 'admin':
            member.role = 'user'
    await db.flush()


#: The levels ``User.role`` may be given through the API. ``manager`` gates
#: real endpoints — closing an inventory period, editing the document profile,
#: cancelling a purchase order — and is offered as an approval-stage role, so a
#: role that guards work nobody can be granted would force every warehouse
#: clerk to be an admin.
VALID_MEMBER_ROLES = frozenset({'admin', 'manager', 'user', 'viewer'})


async def change_member_role_audited(
    db: AsyncSession,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    member_id: UUID,
    role: str | None,
    role_id: UUID | None,
) -> User:
    """Change a member's role and write the journal entry in one transaction.

    Accepts either a built-in level (*role*) or an org-scoped custom role
    (*role_id*). An administrator may not change their own role: demoting
    themselves can lock the organization out of its own settings with one
    click and no way back.
    """
    from app.services.permissions_service import org_role_map_async
    from app.services.user_service import UserService

    lang = get_current_lang()
    if role is not None and role not in VALID_MEMBER_ROLES:
        raise catalogue_refusal(
            'invalid_role', roles=', '.join(sorted(VALID_MEMBER_ROLES))
        )
    if member_id == actor_user_id:
        raise catalogue_refusal('cannot_change_own_role')

    member = await UserService.get_by_id_in_org_async(db, member_id, organization_id)
    if not member:
        raise NotFoundException('member', lang)

    previous_role = member.role
    # Both paths remove a custom role — a built-in level and another custom
    # role each drop the links this member holds — so both entries name the
    # one that went away. Read unconditionally: a swap to another custom role
    # arrives as `role_id` alone. Read before the service drops the links.
    held = await org_role_map_async(
        db, organization_id=organization_id, user_ids=[member.id]
    )
    removed_role = held.get(member.id)
    try:
        await change_member_role(
            db,
            member,
            role,
            organization_id,
            role_id=role_id,
            actor_user_id=actor_user_id,
        )
    except ValueError as exc:
        # A role_id that does not exist here or belongs to another
        # organization (assign_role_async refuses both).
        raise catalogue_refusal('role_not_in_organization') from exc
    # The side the member landed on is named the way the side they left is: a
    # role is deletable and the journal is opened months later, so the name is
    # written with the entry (`role_name` beside `role_id`,
    # docs/subsystems/AUDIT.md).
    assigned_role = None
    if role_id is not None:
        held_after = await org_role_map_async(
            db, organization_id=organization_id, user_ids=[member.id]
        )
        assigned_role = held_after.get(member.id)
    await log_action_async(
        db,
        organization_id=organization_id,
        user_id=actor_user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.ORG_MEMBER,
        target_id=member_id,
        snapshot={
            'name': member.email,
            'before': {
                'role': previous_role,
                **(
                    {
                        'role_id': str(removed_role.id),
                        'role_name': removed_role.name,
                    }
                    if removed_role
                    else {}
                ),
            },
            'after': {
                'role': member.role,
                # Only when a custom role was assigned — the built-in path
                # keeps the historical {'role': ...} snapshot shape.
                **(
                    {
                        'role_id': str(role_id),
                        'role_name': assigned_role.name if assigned_role else None,
                    }
                    if role_id
                    else {}
                ),
            },
        },
    )
    return member
