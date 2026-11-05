from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import UUID

from sqlalchemy import case, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.config import settings
from app.core.async_utils import run_sync_in_thread
from app.core.exceptions import (
    ServiceRejectionError,
    catalogue_refusal,
)
from app.core.logging import get_logger
from app.core.token_blacklist import token_blacklist
from app.core.utils import pick_by_lang
from app.i18n.service import get_error_message
from app.models.organization import Organization, OrganizationInvitation
from app.models.user import RegistrationRequest, User
from app.schemas.user import RegistrationRequestCreate, UserCreate
from app.services.token_service import (
    create_password_reset_token,
    get_password_hash,
    read_password_reset_claims,
    verify_password,
)

logger = get_logger(__name__)

MAX_FAILED_ATTEMPTS = 10
LOCKOUT_DURATION_MINUTES = 30


def default_organization_name(full_name: str | None, lang: str | None = None) -> str:
    """The name of the organization a self-registered account starts with.

    A blank name must not be glued to the possessive: "My's Organization"
    is no one's name. The command-line `create-admin` uses the same
    "My Organization" fallback. The name is stored, so it is written in the
    language the person registered in: a Polish reader was offered
    "Piotr Nowak's Organization" on the first screen.
    """
    name = (full_name or '').strip()
    language = lang or 'en'
    if not name:
        return pick_by_lang(
            language,
            en='My Organization',
            pl='Moja organizacja',
            de='Meine Organisation',
            fr='Mon organisation',
            es='Mi organización',
        )
    return pick_by_lang(
        language,
        en=f"{name}'s Organization",
        pl=f'Organizacja: {name}',
        de=f'Organisation von {name}',
        fr=f'Organisation de {name}',
        es=f'Organización de {name}',
    )


def _is_locked_out(user: User) -> bool:
    """True while the account is temporarily locked after failed attempts.

    This used to raise ``PermissionError``, which the router turned into a
    403 with a specific message — before any password was checked, so an
    attacker could tell an existing account from a non-existent one (and
    read its state) without credentials. The caller now folds it into the
    same "no user" answer as a wrong password.
    """
    return bool(
        user.failed_login_count is not None
        and user.failed_login_count >= MAX_FAILED_ATTEMPTS
        and user.locked_until is not None
        and user.locked_until > datetime.now(UTC)
    )


async def _record_failed_attempt_async(
    db: AsyncSession, user: User, client_ip: str | None = None
) -> None:
    """Async: increment failed login counter and lock account if threshold exceeded.

    The increment is one atomic UPDATE: the database reads and writes the
    count in a single statement, so N failures landing together leave the
    counter at N. The old read-add-write computed every increment from the
    copy each caller had loaded, and all but the last of a concurrent burst
    were overwritten — the lockout arrived later than the threshold. The
    re-lock rides the same statement as a conditional, so no attempt can
    slip between the count crossing the threshold and the lock being set.

    The write is left to the caller's transaction like any other, and the
    login route commits it before it answers with the 401: an exception
    unwinds ``get_async_db`` (``app/database.py``) before its post-yield
    commit runs, so an attempt that was only flushed was always rolled back,
    which switched the lockout off for every caller coming through the API.

    The columns just written are put back on the caller's instance with
    ``set_committed_value``: a plain assignment would mark it dirty, and this
    session's next flush would then write its stale count over a concurrent
    increment — the very loss the atomic statement is here to prevent.
    """
    new_count = func.coalesce(User.failed_login_count, 0) + 1
    result = await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            failed_login_count=new_count,
            locked_until=case(
                (
                    new_count >= MAX_FAILED_ATTEMPTS,
                    datetime.now(UTC) + timedelta(minutes=LOCKOUT_DURATION_MINUTES),
                ),
                else_=User.locked_until,
            ),
        )
        .returning(User.failed_login_count, User.locked_until)
        .execution_options(synchronize_session=False)
    )
    row = result.one_or_none()
    if row is None:
        # The account was deleted while the password was being checked;
        # there is no counter left to advance.
        return
    count, locked_until = row
    set_committed_value(user, 'failed_login_count', count)
    set_committed_value(user, 'locked_until', locked_until)

    ip = client_ip or 'unknown'
    if count >= MAX_FAILED_ATTEMPTS:
        logger.warning(
            'Account locked for user %s after %d failed login attempts from IP %s',
            user.email,
            count,
            ip,
        )
    logger.warning(
        'Failed login attempt #%d for user %s from IP %s',
        count,
        user.email,
        ip,
    )


async def _clear_failed_attempts_async(db: AsyncSession, user: User) -> None:
    """Async: reset failed login counter after successful authentication."""
    if user.failed_login_count:
        user.failed_login_count = 0
        user.locked_until = None
        await db.flush()


async def authenticate_user_async(
    db: AsyncSession, email: str, password: str, client_ip: str | None = None
) -> User | None:
    """Async: authenticate a user by email and password."""
    user = await db.scalar(select(User).where(User.email == email))
    if not user:
        dummy_hash = '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWrn96pzvCpJQ7Z3tilM9UAVhQ.qAA'
        # The equalising round costs the same ~0.25 s as a real check, so it
        # leaves the loop the same way — in the thread pool, where it cannot
        # stall every other request the worker is serving.
        await run_sync_in_thread(partial(verify_password, 'dummy_password', dummy_hash))
        return None

    # Hash first, decide after: returning early on a locked account skipped
    # the bcrypt round, so a locked account answered measurably faster than
    # a wrong password — a weaker version of the oracle the uniform 401
    # closed. The rate limiter caps how often anyone can sample it, but the
    # cheaper fix is simply not to have a fast path.
    password_ok = await run_sync_in_thread(
        partial(verify_password, password, user.hashed_password)
    )

    if _is_locked_out(user):
        return None

    if not password_ok:
        await _record_failed_attempt_async(db, user, client_ip)
        return None

    # A blocked or deactivated user must not obtain a fresh token.
    # The refusal is the same 401 as a wrong password — telling the
    # caller *why* login failed is what let an attacker map account states.
    # Authenticated requests still get the specific 403 (verify_token_async),
    # which is after authentication and therefore not an oracle.
    if user.is_blocked or not user.is_active:
        return None

    await _clear_failed_attempts_async(db, user)
    return user


def refuse_credential_change_in_demo() -> None:
    """Refuse a password change or reset on the public demo.

    Every e-mail a demo sends lands in the public Mailpit inbox, so a reset
    link there would hand the operator's account, or a visitor's sandbox
    account, to whoever opens it first; a password change is closed with it.
    Visitors need no account of their own. Declared through
    ``settings.INVENTARI_DEMO``, like the SMTP lock.
    """
    if settings.INVENTARI_DEMO:
        raise catalogue_refusal('demo_credentials_locked')


class AuthService:
    @staticmethod
    async def email_exists_async(db: AsyncSession, email: str) -> bool:
        result = await db.scalar(select(User).where(User.email == email))
        return result is not None

    @staticmethod
    async def find_usable_invitation_async(
        db: AsyncSession, code: str, email: str
    ) -> OrganizationInvitation | None:
        """The invitation *code* opens for *email*, or nothing.

        An invitation is the one thing that lets an account be created here
        without an operator approving it: the administrator gave that approval
        in advance, to one named person. So this path enforces exactly what
        joining enforces — not expired, not spent, not withdrawn, and issued
        for the address registering. Anything weaker and the address binding
        would guard only the account that already exists, while a leaked link
        still bought a brand-new one.

        Invitations minted before they carried an address have none and stay
        bearer codes until they expire.
        """
        # Locked for the same reason joining locks it: the caller keeps the
        # row unspent while it creates the account, so two registrations with
        # one code would otherwise both find it free.
        invitation = await db.scalar(
            select(OrganizationInvitation)
            .where(
                OrganizationInvitation.code == code,
                OrganizationInvitation.expires_at > datetime.now(UTC),
                OrganizationInvitation.is_used.is_(False),
                OrganizationInvitation.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if invitation is None:
            return None
        if invitation.invited_email and (
            invitation.invited_email.casefold() != email.casefold()
        ):
            return None
        return invitation

    @staticmethod
    async def get_user_count_async(db: AsyncSession) -> int:
        return await db.scalar(select(func.count(User.id))) or 0

    @staticmethod
    async def has_registration_request_async(db: AsyncSession, email: str) -> bool:
        """Whether a request that has not been rejected holds this address.

        A rejected row stays on file (the address is unique) but holds nothing:
        the person may ask again, and the new request reopens that row.
        """
        result = await db.scalar(
            select(RegistrationRequest.id).where(
                RegistrationRequest.email == email,
                RegistrationRequest.is_rejected.is_(False),
            )
        )
        return result is not None

    @staticmethod
    async def get_pending_requests_async(
        db: AsyncSession,
    ) -> list[RegistrationRequest]:
        result = await db.scalars(
            select(RegistrationRequest)
            .where(
                RegistrationRequest.is_rejected.is_(False),
                # Approved but not yet completed (the token is cleared on use):
                # the administrator can approve again to get a fresh link.
                or_(
                    RegistrationRequest.accepted_at.is_(None),
                    RegistrationRequest.token.is_not(None),
                ),
            )
            .order_by(RegistrationRequest.created_at)
        )
        return list(result.all())

    @staticmethod
    async def get_request_by_id_async(
        db: AsyncSession, request_id: str
    ) -> RegistrationRequest | None:
        return await db.scalar(
            select(RegistrationRequest).where(RegistrationRequest.id == request_id)
        )

    @staticmethod
    async def get_request_by_token_async(
        db: AsyncSession, token: str
    ) -> RegistrationRequest | None:
        return await db.scalar(
            select(RegistrationRequest).where(
                RegistrationRequest.token == token,
                RegistrationRequest.expires_at > datetime.now(UTC),
            )
        )

    @staticmethod
    async def get_org_smtp_config_async(
        db: AsyncSession, organization_id: UUID | None
    ) -> dict | None:
        """The organization's SMTP settings, decrypted for sending.

        The password leaf is read strictly and downgraded HERE, at the one
        caller that acts on it: an unreadable password (a rotation since it
        was saved) logs the reason an administrator can act on instead of
        letting mail fail as "not configured" while the host, user and
        masked password all still sit in the form. The rest of the blob
        stays on the lenient walk — those leaves render, this one acts.
        """
        if not organization_id:
            return None
        from app.services.crypto_service import (
            UndecryptableSecretError,
            decrypt_settings,
            decrypt_value,
        )

        org = await db.scalar(
            select(Organization).where(Organization.id == organization_id)
        )
        if not org or not org.settings:
            return None
        decrypted = decrypt_settings(org.settings)
        smtp = decrypted.get('smtp')
        stored_password = (
            org.settings.get('smtp', {}).get('password')
            if isinstance(org.settings.get('smtp'), dict)
            else None
        )
        if isinstance(smtp, dict) and stored_password:
            try:
                smtp['password'] = decrypt_value(stored_password)
            except UndecryptableSecretError:
                logger.warning(
                    'The organization SMTP password cannot be decrypted '
                    '(the encryption key or salt has rotated since it was '
                    'saved) — mail will not send until the password is '
                    're-entered in Settings → Email.'
                )
                smtp['password'] = ''
        return smtp

    @staticmethod
    async def mail_delivery_available_async(db: AsyncSession) -> bool:
        """Whether this installation can send mail for anyone.

        The installation's own mail server, or the server any organization
        configured in Settings. Public screens ask this before they promise a
        letter, and they cannot name an organization: the caller is anonymous,
        and answering per address would tell a prober which addresses hold
        accounts. Reading only the system settings said "no mail here" on an
        installation whose administrator had set mail up through Settings.
        """
        from app.services.email_service import EmailService

        if EmailService.is_configured():
            return True
        # Organizations that never saved a mail server have no host leaf, so
        # the filter leaves the scan to those that did.
        organization_ids = await db.scalars(
            select(Organization.id).where(
                Organization.settings['smtp']['host'].as_string().is_not(None)
            )
        )
        for organization_id in organization_ids.all():
            smtp = await AuthService.get_org_smtp_config_async(db, organization_id)
            if EmailService.is_configured(smtp):
                return True
        return False

    @staticmethod
    async def register_user_async(
        db: AsyncSession,
        user_in: UserCreate,
        registration_request: RegistrationRequest | None = None,
    ) -> User:
        target_organization_id = None
        invitation: OrganizationInvitation | None = None
        if user_in.invite_code:
            # A consumed code must not admit anyone else within its validity
            # window — the join flow already filters is_used; this path
            # used to skip the filter and never burn the code at all.
            invitation = await AuthService.find_usable_invitation_async(
                db, user_in.invite_code, user_in.email
            )
            if invitation:
                target_organization_id = invitation.organization_id

        # Serialize first-user detection so two concurrent registrations on an
        # empty DB cannot both observe count==0 and both become superuser.
        # pg_advisory_xact_lock auto-releases at commit/rollback. The key is a
        # fixed magic int scoped to the "first user" critical section.
        await db.execute(text('SELECT pg_advisory_xact_lock(727272)'))
        is_first_user = await db.scalar(select(func.count(User.id))) == 0

        # Three ways to earn an account: be the first one, hold a valid invite,
        # or have an operator approve a registration request. The router checks
        # this too, ahead of the address lookup so the refusal carries no
        # information; re-checked here under the lock, which is where
        # `is_first_user` is finally decided — two registrations racing on an
        # empty installation both pass the router gate, and the loser must not
        # fall through into an account nobody granted.
        if not (is_first_user or target_organization_id or registration_request):
            raise catalogue_refusal(
                'organization_invite_invalid', lang=user_in.preferred_language
            )

        hashed_password = await run_sync_in_thread(
            partial(get_password_hash, user_in.password)
        )
        user = User(
            email=user_in.email,
            hashed_password=hashed_password,
            full_name=user_in.full_name,
            preferred_language=user_in.preferred_language,
            role='admin' if is_first_user else 'user',
            is_superuser=is_first_user,
            # Active on arrival: the guard above already established that this
            # is a first user, an invited one, or an approved one (an
            # approved registration carries a token minted in
            # approve_registration_request_async and cleared on use/reject).
            is_active=True,
        )
        db.add(user)
        await db.flush()

        if target_organization_id:
            user.organization_id = target_organization_id
            if invitation is not None:
                # The role the inviter chose, not a constant — mirrors
                # join_organization. The first user keeps 'admin' regardless:
                # an installation owner must not land as a plain member of the
                # organization they were invited to before it existed.
                if not is_first_user:
                    user.role = invitation.role or 'user'
                # Burn the code so nobody else can redeem it. Who
                # walked through the door, and when — the join path keeps
                # both, and a newcomer's arrival is the one arrival this
                # organization could not name at all.
                invitation.is_used = True
                invitation.used_by_user_id = user.id
                invitation.used_at = datetime.now(UTC)
                # The log held only the issuing of the invitation; the act
                # that granted access went unrecorded. Mirrors the creation
                # entry, which points at the organization and keeps the code
                # itself out of it.
                from app.core.contracts import AuditAction, AuditTargetType
                from app.core.public_api import core_api
                from app.services._org_membership import (
                    invitation_role_label_async,
                )

                await core_api.audit_log.log_action_async(
                    db,
                    organization_id=invitation.organization_id,
                    user_id=user.id,
                    action=AuditAction.USE,
                    target_type=AuditTargetType.INVITATION,
                    target_id=invitation.id,
                    snapshot={
                        'invited_email': invitation.invited_email,
                        'role': await invitation_role_label_async(db, invitation),
                    },
                )
        else:
            from app.services._org_writes import (
                generate_short_id,
                seed_new_organization_async,
            )

            org_name = default_organization_name(
                user.full_name, user.preferred_language
            )
            organization = Organization(
                name=org_name, created_by=user.id, short_id=generate_short_id()
            )
            db.add(organization)
            await db.flush()
            user.organization_id = organization.id
            user.role = 'admin'
            await seed_new_organization_async(db, organization.id)

        if registration_request:
            registration_request.token = None
        await db.flush()

        if invitation is not None and invitation.role_id:
            # The custom role the inviter picked goes on top of the enum base
            # level. Mirrors join_organization: if the role vanished meanwhile
            # (SET NULL keeps the column clean, but a flush race is still
            # possible), the member keeps the enum level.
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
                    'Invitation %s names role %s that no longer fits organization %s — registered with enum level only',
                    invitation.code,
                    invitation.role_id,
                    invitation.organization_id,
                )

        await db.refresh(user)
        return user

    @staticmethod
    async def create_registration_request_async(
        db: AsyncSession, request_in: RegistrationRequestCreate
    ) -> RegistrationRequest:
        # A rejected request keeps the unique address, so asking again reopens
        # that row instead of inserting a second one; it reaches the queue as
        # a fresh request, with the name and language the person gave this time.
        new_request = await db.scalar(
            select(RegistrationRequest).where(
                RegistrationRequest.email == request_in.email
            )
        )
        if new_request is None:
            new_request = RegistrationRequest(email=request_in.email)
            db.add(new_request)
        new_request.full_name = request_in.full_name
        new_request.preferred_language = request_in.preferred_language
        new_request.is_rejected = False
        new_request.rejected_at = None
        # An approval that was withdrawn by a rejection must not leave the row
        # looking approved: the queue hides an accepted row with no token.
        new_request.accepted_at = None
        new_request.approved_by_id = None
        new_request.expires_at = None
        new_request.token = None
        new_request.created_at = datetime.now(UTC)
        await db.flush()
        await db.refresh(new_request)

        try:
            from app.services.notification_service import notification_service

            lang = request_in.preferred_language
            # A savepoint: the notice is best-effort, and a write of its that
            # fails must not take the request it announces down with it.
            async with db.begin_nested():
                admin_notifications = (
                    await notification_service.notify_superusers_async(
                        db,
                        title=get_error_message('reg_request_new_title', lang),
                        content=get_error_message(
                            'reg_request_new_content',
                            lang,
                            name=new_request.full_name or new_request.email,
                        ),
                        type='warning',
                        link='/settings#registration-requests',
                    )
                )
            from app.core.public_api import core_api

            await core_api.notifications.publish_async(
                db,
                [notification_service.to_dto(n) for n in admin_notifications],
            )
        except Exception as exc:  # noqa: BLE001 — the notice is best-effort; the request stands
            logger.warning(
                'Failed to notify admins about new registration request: %s', exc
            )

        return new_request

    @staticmethod
    async def approve_registration_request_async(
        db: AsyncSession, request: RegistrationRequest, approver_id: UUID
    ) -> str:
        import secrets

        token = secrets.token_urlsafe(32)

        request.token = token
        request.accepted_at = datetime.now(UTC)
        request.expires_at = datetime.now(UTC) + timedelta(days=7)
        request.approved_by_id = approver_id
        request.is_rejected = False
        await db.flush()
        return token

    @staticmethod
    async def reject_registration_request_async(
        db: AsyncSession, request: RegistrationRequest
    ) -> None:
        request.is_rejected = True
        request.rejected_at = datetime.now(UTC)
        request.token = None
        await db.flush()

    @staticmethod
    async def get_profile_async(db: AsyncSession, user_id: UUID) -> User:
        user = await db.scalar(select(User).where(User.id == user_id))
        if not user:
            raise ServiceRejectionError('user_not_found')
        return user

    @staticmethod
    async def update_user_profile_async(
        db: AsyncSession, user_id: UUID, update_data: dict
    ) -> User:
        user = await db.scalar(select(User).where(User.id == user_id))
        if not user:
            raise ServiceRejectionError('user_not_found')

        if 'full_name' in update_data:
            user.full_name = update_data['full_name']
        if 'password' in update_data:
            refuse_credential_change_in_demo()
            # Re-authenticate before a password change. Without this a
            # hijacked session was enough to take the account over outright.
            current_password = update_data.get('current_password')
            if current_password:
                current_ok = await run_sync_in_thread(
                    partial(verify_password, current_password, user.hashed_password)
                )
            else:
                current_ok = False
            if not current_ok:
                # ValidationException (400), not ValueError — the router maps a
                # bare ValueError from this method to 404 "user not found".
                raise catalogue_refusal(
                    'current_password_incorrect', field='current_password'
                )
            user.hashed_password = await run_sync_in_thread(
                partial(get_password_hash, update_data['password'])
            )
        update_data.pop('current_password', None)
        if 'preferred_language' in update_data:
            user.preferred_language = update_data['preferred_language']
        await db.flush()
        await db.refresh(user)
        # Only a password change invalidates other sessions — editing
        # a display name must not log the user out of every device. Ahead
        # of the caller's commit, so a store that is down fails the change
        # instead of leaving the old sessions alive beside a new password.
        if 'password' in update_data:
            await token_blacklist.mark_credentials_changed(str(user.id))
        return user

    @staticmethod
    async def request_password_reset_async(
        db: AsyncSession, email: str
    ) -> tuple[str, str, UUID | None] | None:
        """Look up the user by email and create a short-lived reset token.

        Returns ``(token, preferred_language, organization_id)`` when a
        matching user is found, or ``None`` when the email is unknown.
        The router treats both cases as success (202) so the endpoint
        never reveals whether an account exists for a given address.
        Preferred language is bundled here so the router can pick the
        right email translation without touching the User model
        directly; the organization id travels with it so the reset mail
        can be tagged for the tenant that owns the account.
        """
        user = await db.scalar(select(User).where(User.email == email))
        if not user:
            return None
        return (
            create_password_reset_token(user.id),
            user.preferred_language or 'en',
            user.organization_id,
        )

    @staticmethod
    async def confirm_password_reset_async(
        db: AsyncSession, token: str, new_password: str
    ) -> User:
        """Verify a reset token and replace the user's password.

        Raises ``ValueError`` for any failure mode (invalid token, unknown
        user) so the router can map it to a 400. On success the new hash is
        flushed for the caller to commit; the returned instance reflects it.
        """
        refuse_credential_change_in_demo()
        claims = read_password_reset_claims(token)
        if not claims:
            raise ServiceRejectionError('invalid_reset_token')
        user_id, jti, expires_at = claims
        # A reset token is single-use. Without this a leaked link
        # kept working for its full 30-minute window, however often replayed.
        if await token_blacklist.is_revoked(jti):
            raise ServiceRejectionError('invalid_reset_token')
        user = await db.get(User, user_id)
        if not user:
            raise ServiceRejectionError('invalid_reset_token')
        user.hashed_password = await run_sync_in_thread(
            partial(get_password_hash, new_password)
        )
        await db.flush()
        await db.refresh(user)
        # A reset is the incident-response path — every session issued
        # before it (including an attacker's stolen refresh token) dies here,
        # ahead of the caller's commit: a store that is down fails the reset
        # rather than leaving those sessions alive beside the new password.
        await token_blacklist.mark_credentials_changed(str(user.id))
        await token_blacklist.revoke(jti, expires_at)
        return user
