from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, EmailStr, model_validator
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_current_admin_user, get_superuser
from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    SystemPermission,
    UserContextDTO,
)
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_permission,
)
from app.core.exceptions import (
    AppException,
    ConflictException,
    NotFoundException,
    ServiceRejectionError,
    catalogue_refusal,
    catalogue_status_refusal,
    refusal_code,
    refusal_text,
)
from app.core.file_signature import validate_signature
from app.core.limiter import limiter
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.core.upload_validation import read_capped_upload
from app.i18n.service import get_current_lang, get_error_message
from app.schemas._common import (
    LogoUploadResponse,
    MessageResponse,
    TestEmailResponse,
)
from app.schemas._smtp import SmtpConfig
from app.schemas.organization import (
    FailedEmailSummary,
    InvitationSummary,
    OrganizationCreate,
    OrganizationMember,
    OrganizationUpdate,
)
from app.schemas.organization import (
    Organization as OrganizationSchema,
)
from app.schemas.pagination import PaginatedResponse
from app.services._org_membership import (
    VALID_MEMBER_ROLES,
    change_member_role_audited,
    invitation_role_label_async,
)
from app.services._org_membership import (
    create_invitation_code as create_invitation_code_service,
)
from app.services._org_membership import (
    join_organization as join_organization_service,
)
from app.services._org_membership import (
    leave_organization as leave_organization_service,
)
from app.services._org_membership import (
    list_invitations as list_invitations_service,
)
from app.services._org_membership import (
    remove_member as remove_member_service,
)
from app.services._org_membership import (
    resend_invitation as resend_invitation_service,
)
from app.services._org_membership import (
    revoke_invitation as revoke_invitation_service,
)
from app.services._org_writes import (
    create_default_locations,
    refuse_smtp_settings_in_demo,
    set_organization_logo,
    update_organization_audited,
)
from app.services._org_writes import (
    create_organization as create_organization_service,
)
from app.services.crypto_service import mask_settings
from app.services.user_service import UserService

#: Hand-synced with the frontend gate (see the unit test that pins the
#: number) and with the other interface-image limits: ten megabytes,
#: because phones take bigger photos than five.
_MAX_LOGO_BYTES = 10 * 1024 * 1024

logger = get_logger(__name__)

router = APIRouter()


class InvitationCodeResponse(BaseModel):
    code: str
    expires_at: str | None = None
    role: str = 'user'
    role_id: str | None = None
    invited_email: str | None = None
    # Whether the mail queue accepted the invitation — not whether it was
    # delivered. False when the organization has no SMTP at all or the queue
    # refused the row, and the screen then hands the administrator the link to
    # pass on themselves.
    email_sent: bool = False


class InvitationCodeRequest(BaseModel):
    """Who the code is for, and what the account redeeming it becomes.

    ``role`` is the built-in base level; ``role_id`` optionally names an
    org-scoped custom role the join assigns on top of it. ``email`` is the
    address the code is bound to — only an account with that address can
    redeem it.
    """

    role: str = 'user'
    role_id: UUID | None = None
    email: EmailStr | None = None


class MemberRoleUpdate(BaseModel):
    """A built-in level (``role``) or an org-scoped custom role (``role_id``).

    Exactly one of the two: a member carries either a level from
    ``VALID_MEMBER_ROLES`` or one custom role — picking the enum clears the
    custom links, picking a custom role replaces the previous one.
    """

    role: str | None = None
    role_id: UUID | None = None

    @model_validator(mode='after')
    def _exactly_one(self) -> 'MemberRoleUpdate':
        if (self.role is None) == (self.role_id is None):
            raise ServiceRejectionError('member_role_exactly_one')
        return self


class MemberRoleResponse(BaseModel):
    message: str
    user_id: str
    role: str
    role_id: str | None = None


class RemoveMemberResponse(BaseModel):
    message: str
    user_id: str


@router.get('/all', response_model=PaginatedResponse[OrganizationSchema])
async def list_all_organizations(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_superuser),
    db=Depends(get_async_db, scope='function'),
):
    page = PaginatedResponse.from_full_list(
        await core_api.organizations.list_all_async(db), offset=offset, limit=limit
    )
    for org in page.items:
        org.member_count = await core_api.users.count_async(db, org.id) or 0
    return page


@router.post('', response_model=OrganizationSchema, status_code=status.HTTP_201_CREATED)
async def create_organization(
    organization_in: OrganizationCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    lang = get_current_lang()
    if current_user.organization_id:
        raise ConflictException(
            code='USER_ALREADY_IN_ORGANIZATION',
            message=get_error_message('user_already_in_organization', lang),
        )

    refuse_smtp_settings_in_demo(organization_in.settings)

    db_user_model = await UserService.get_by_id_model_async(db, current_user.id)
    if db_user_model is None:
        raise catalogue_status_refusal('user_not_found', 404)

    org = await create_organization_service(db, organization_in, db_user_model)
    # Deferred columns need to be refreshed inside the async session
    await db.refresh(org, list(core_api.organizations.deferred_dto_columns))
    return org


@router.post('/my/test-email', response_model=TestEmailResponse)
async def send_test_email(
    smtp_config: SmtpConfig = Body(...),
    current_user: UserContextDTO = Depends(get_current_admin_user),
):
    from app.services.email_service import email_service

    subject = 'Inventari - Test Email'
    html_content = f"""
    <html>
        <body>
            <h2 style="color: #2563eb;">Test successful!</h2>
            <p>Your SMTP configuration is correct.</p>
            <p>Sent to: <b>{current_user.email}</b></p>
            <hr>
            <p style="font-size: 12px; color: #999;">Inventari System Test</p>
        </body>
    </html>
    """

    result = await run_in_threadpool(
        email_service.deliver,
        current_user.email or '',
        subject,
        html_content,
        smtp_config=smtp_config.model_dump(exclude_none=True),
    )

    if not result.ok:
        # The reason travels with the refusal: "it failed" leaves an
        # administrator guessing between a wrong password, a closed port and a
        # host that never answered.
        message = get_error_message('email_test_failed', get_current_lang())
        if result.error:
            message = f'{message}: {result.error}'
        raise AppException(
            status_code=502,
            code='EMAIL_SEND_FAILED',
            message=message,
        )

    return TestEmailResponse(message='Test email sent successfully')


async def _mail_the_invitation(
    db,
    current_user: UserContextDTO,
    invitation: dict,
) -> bool:
    """Hand the invitation to the mail queue, if there is one to hand it to.

    Returns whether the queue took the row, not whether anything arrived:
    delivery belongs to the worker, which retries a failed send on its own.
    An installation without SMTP is a supported installation: the invitation
    is created either way and the administrator passes the link on themselves.
    Nor does a refusal undo the invitation — the code exists, it works, and
    telling the administrator that nothing was created would be a lie they
    would act on by issuing a second one.
    """
    if not invitation.get('invited_email'):
        return False

    from app.services.auth_service import AuthService
    from app.services.email_service import email_service

    smtp_config = await AuthService.get_org_smtp_config_async(
        db, current_user.organization_id
    )
    if not email_service.is_configured(smtp_config):
        return False

    organization = current_user.organization
    try:
        return await email_service.send_invitation_async(
            invitation['invited_email'],
            f'/join?code={invitation["code"]}',
            organization_name=organization.name if organization else 'Inventari',
            role=invitation.get('role_label') or invitation.get('role') or 'user',
            lang=get_current_lang(),
            smtp_config=smtp_config,
            organization_id=current_user.organization_id,
        )
    except Exception:  # the invitation stands; mailing it is best-effort
        logger.exception('Invitation created but could not be mailed to its recipient')
        return False


@router.post('/my/invitation-code', response_model=InvitationCodeResponse)
@limiter.limit('10/hour')
async def create_invitation_code(
    request: Request,
    body: InvitationCodeRequest = Body(default_factory=InvitationCodeRequest),
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    lang = get_current_lang()
    if not current_user.organization_id:
        raise NotFoundException('organization', lang)

    if body.role not in VALID_MEMBER_ROLES:
        raise catalogue_refusal(
            'invalid_role', roles=', '.join(sorted(VALID_MEMBER_ROLES))
        )

    from app.core.contributions import contribution_registry

    if not await contribution_registry.check_quota(
        current_user.organization_id, 'max_members', db
    ):
        raise ConflictException(
            code='ORG_MEMBER_LIMIT',
            message=get_error_message('organization_member_limit', get_current_lang()),
        )

    invitation = await create_invitation_code_service(
        db,
        current_user.organization_id,
        current_user.id,
        body.role,
        body.role_id,
        invited_email=str(body.email) if body.email else None,
    )

    # Handing out a way into the organization is an administrative act, and
    # the log held nothing about it. The code itself never goes in —
    # an audit entry a reader can use to join is not an audit entry.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.INVITATION,
        target_id=invitation['id'],
        snapshot={
            'expires_at': invitation.get('expires_at'),
            'role': invitation.get('role_label') or invitation.get('role'),
            'invited_email': invitation.get('invited_email'),
        },
    )
    # Last: the mail queue commits on its own, and nothing after it may fail
    # and take back the invitation the mail already carries.
    invitation['email_sent'] = await _mail_the_invitation(db, current_user, invitation)
    return invitation


@router.get('/my/invitations', response_model=PaginatedResponse[InvitationSummary])
async def list_invitations(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    """Invitations issued for this organization, newest first.

    The screen showed a freshly generated link and nothing else: whether an
    earlier one had been used, or was still live, could only be inferred from
    who turned up in the member list.
    """
    if not current_user.organization_id:
        raise NotFoundException('organization', get_current_lang())
    invitations = await list_invitations_service(db, current_user.organization_id)
    return PaginatedResponse.from_full_list(invitations, offset=offset, limit=limit)


@router.get('/my/failed-emails', response_model=PaginatedResponse[FailedEmailSummary])
async def list_failed_emails(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    """Mail this organization sent that never arrived, newest first.

    The queue retries for about seven and a half minutes and then marks the
    row failed. Until this read existed that was the end of the message for
    everyone outside the container log: an invitation nobody received, a
    password-reset link that locked its user out, and an administrator with
    no way to learn either had happened.
    """
    if not current_user.organization_id:
        raise NotFoundException('organization', get_current_lang())
    from app.services.email_jobs import list_failed_jobs_async

    jobs, total = await list_failed_jobs_async(
        db, current_user.organization_id, offset=offset, limit=limit
    )
    return PaginatedResponse.from_slice(jobs, offset, limit, total)


@router.post(
    '/my/invitations/{invitation_id}/resend', response_model=InvitationCodeResponse
)
@limiter.limit('10/hour')
async def resend_invitation(
    request: Request,
    invitation_id: UUID,
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    """Send a pending invitation again and give it another seven days.

    Rate-limited like issuing one: the endpoint puts mail in somebody else's
    inbox on request, and an uncapped one is a way to fill it.
    """
    lang = get_current_lang()
    if not current_user.organization_id:
        raise NotFoundException('organization', lang)

    from app.services.auth_service import AuthService
    from app.services.email_service import email_service

    smtp_config = await AuthService.get_org_smtp_config_async(
        db, current_user.organization_id
    )
    # Checked before the invitation is touched: extending an invitation that
    # cannot be sent would report success for a message nobody will receive.
    if not email_service.is_configured(smtp_config):
        raise catalogue_refusal('smtp_not_configured')

    try:
        invitation = await resend_invitation_service(
            db,
            current_user.organization_id,
            invitation_id,
            actor_user_id=current_user.id,
        )
    except ValueError as exc:
        raise NotFoundException('invitation', lang) from exc

    invitation['email_sent'] = await _mail_the_invitation(db, current_user, invitation)
    return invitation


@router.delete('/my/invitations/{invitation_id}', status_code=204)
async def revoke_invitation(
    invitation_id: UUID,
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
) -> None:
    """Withdraw an invitation that nobody has redeemed yet.

    A code used to be a fifteen-minute affair, so taking one back was a matter
    of waiting. Living a week, it needs a way out: an address typed wrong, a
    person who left before arriving, a role chosen by mistake.
    """
    lang = get_current_lang()
    if not current_user.organization_id:
        raise NotFoundException('organization', lang)

    try:
        invitation = await revoke_invitation_service(
            db, current_user.organization_id, invitation_id
        )
    except ValueError as exc:
        raise NotFoundException('invitation', lang) from exc

    # The row leaves the list on revocation, so "who took this invitation
    # back" has nowhere else to live. The code stays out of the snapshot for
    # the same reason it stays out of the creation entry.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=AuditAction.SOFT_DELETE,
        target_type=AuditTargetType.INVITATION,
        target_id=invitation.id,
        snapshot={
            'invited_email': invitation.invited_email,
            'role': await invitation_role_label_async(db, invitation),
        },
    )


@router.post('/join', response_model=OrganizationSchema)
@limiter.limit('10/hour')
async def join_organization(
    request: Request,
    code: str = Body(..., embed=True),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Join an organization with an invitation code.

    Rate-limited like code creation: a failed attempt costs the caller nothing
    and does not consume the code, so without a cap the validity window is a
    free guessing budget. The caller is authenticated here, so the limiter
    buckets by user id rather than by IP — a proxy pool buys no extra guesses,
    only more accounts does, and those now need a bootstrap, an invite or an
    operator's approval.

    Deliberately no per-code failed-attempt counter: 10 guesses/hour/account
    against a 32^8 space is 1680 attempts over the code's whole week, which is
    not a threat, and burning an invitation after N misses would hand anyone
    who can guess *near* a code a way to cancel someone else's.
    """
    try:
        organization = await join_organization_service(db, code, current_user.id)
    except ServiceRejectionError as exc:
        # A live link opened by a different account is not a dead link: the
        # reader is told to sign out and open it again, not to ask for a new one.
        if exc.key == 'invitation_other_address':
            raise ConflictException(
                code=refusal_code(exc, 'INVITATION_OTHER_ADDRESS'),
                message=refusal_text(exc),
            ) from exc
        raise NotFoundException('organization', get_current_lang()) from exc
    except ValueError as exc:
        raise NotFoundException('organization', get_current_lang()) from exc

    # Deferred columns; the response model reads them, and a lazy load at
    # serialisation time is outside the greenlet, so it fails the whole 200
    # the join just earned. The list lives on the model, next to the
    # columns it names.
    await db.refresh(organization, list(core_api.organizations.deferred_dto_columns))
    return organization


@router.get('/my', response_model=OrganizationSchema)
async def get_my_organization(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    lang = get_current_lang()
    if not current_user.organization_id:
        raise NotFoundException('organization', lang)

    organization = current_user.organization
    if not organization:
        raise NotFoundException('organization', lang)
    response = OrganizationSchema.model_validate(organization)
    response.settings = mask_settings(organization.settings or {})
    # Masked settings cannot answer this: the password comes back starred, and
    # an installation-wide mail server does not appear in them at all.
    from app.services.auth_service import AuthService
    from app.services.email_service import email_service

    response.can_send_email = email_service.is_configured(
        await AuthService.get_org_smtp_config_async(db, organization.id)
    )
    return response


@router.post(
    '/current/defaults',
    # list-envelope-exception: a bulk result, the locations this request just seeded
    response_model=list[dict],
)
async def create_default_locations_for_current_organization(
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    """Seed the starting locations declared by the organization's profile.

    Took a module list until, when the set moved to the product
       profile: the modules an organization enables seed their own locations
       through ``system_on_enable``, so the list said nothing here.
    """
    lang = get_current_lang()
    if not current_user.organization_id:
        raise NotFoundException('organization', lang)

    created_locations = await create_default_locations(
        db, current_user.organization_id, current_user.id
    )

    return [{'id': str(loc.id), 'name': loc.name} for loc in created_locations]


@router.get('/my/members', response_model=PaginatedResponse[OrganizationMember])
async def get_organization_members(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=100),
    _: object = require_permission(SystemPermission.ORG_READ),
):
    if not current_user.organization_id:
        return PaginatedResponse(
            items=[], total=0, limit=limit, offset=offset, has_more=False
        )
    members = await core_api.users.list_org_members_async(
        db,
        current_user.organization_id,
        offset=offset,
        limit=limit,
        search=search,
    )
    custom_roles = await core_api.roles.org_role_map_async(
        db,
        organization_id=current_user.organization_id,
        user_ids=[m.id for m in members],
    )
    items = [
        OrganizationMember(
            id=m.id,
            email=m.email,
            full_name=m.full_name,
            role=m.role,
            custom_role=custom_roles.get(m.id),
        )
        for m in members
    ]
    total = await core_api.users.count_async(db, current_user.organization_id)
    return PaginatedResponse.from_slice(
        items=items,
        offset=offset,
        limit=limit,
        total=total,
    )


@router.put('', response_model=OrganizationSchema)
async def update_organization(
    organization_in: OrganizationUpdate,
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    # The organization's general settings, which are administration — and
    # not the AI purpose bindings, although the settings block carries them:
    # those have their own door, `PUT /ai-connections/bindings`, under the
    # narrower `org:settings:write`, and this write keeps them as stored
    # (`_keep_the_ai_bindings` in app.services._org_writes). Two doors to one
    # choice under two keys let each key's holder do the other's work.
    if not current_user.organization_id:
        raise NotFoundException('organization', get_current_lang())

    organization_model = await update_organization_audited(
        db,
        current_user.organization_id,
        organization_in,
        actor_user_id=current_user.id,
    )
    await db.refresh(
        organization_model, list(core_api.organizations.deferred_dto_columns)
    )

    response = OrganizationSchema.model_validate(organization_model)
    response.settings = mask_settings(organization_model.settings or {})
    return response


#: Logo upload: extension derived from the validated MIME, never from the
#: client-supplied filename (same rule as item covers).
_LOGO_MIME_TO_EXT = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/gif': 'gif',
    'image/webp': 'webp',
}


@router.post('/logo', response_model=LogoUploadResponse)
async def upload_organization_logo(
    image: UploadFile = File(...),
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    """Upload the logo printed on documents and other outbound material.

    the issuer block on document printouts needs the organization's
       logo; the file lands in the org-scoped storage and ``logo_url`` keeps the
       path. The PDF service reads the bytes server-side (WeasyPrint cannot load
       external URLs), so the stored value is the storage path, not a URL.
    """
    lang = get_current_lang()
    if not current_user.organization_id:
        raise NotFoundException('organization', lang)

    if not image.content_type or image.content_type not in _LOGO_MIME_TO_EXT:
        raise catalogue_refusal('only_image_files_allowed')

    # Capped while reading, not measured afterwards: `await image.read()`
    # buffers the whole body first, so a body far over the limit is already
    # in memory by the time the limit refuses it.
    try:
        content = await read_capped_upload(image, lang, _MAX_LOGO_BYTES)
    except ValueError as exc:
        from app.core.upload_validation import format_size_limit

        raise AppException(
            status_code=413,
            code='FILE_TOO_LARGE',
            message=get_error_message(
                'image_too_large', lang, limit=format_size_limit(_MAX_LOGO_BYTES)
            ),
        ) from exc
    validate_signature(content, image.content_type)

    ext = _LOGO_MIME_TO_EXT[image.content_type]
    path = await core_api.file_storage.save_for_org_async(
        current_user.organization_id,
        'organizations',
        f'logo.{ext}',
        content,
        image.content_type,
    )

    await set_organization_logo(
        db, current_user.organization_id, path, actor_user_id=current_user.id
    )
    return {'logo_url': path}


@router.delete('/logo', status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization_logo(
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    """Remove the organization logo; documents print without one."""
    lang = get_current_lang()
    if not current_user.organization_id:
        raise NotFoundException('organization', lang)

    await set_organization_logo(
        db, current_user.organization_id, None, actor_user_id=current_user.id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post('/my/leave', response_model=MessageResponse)
async def leave_organization(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    if not current_user.organization_id:
        raise catalogue_refusal('organization_not_found')

    try:
        await leave_organization_service(
            db, current_user.id, current_user.organization_id
        )
    except ValueError as exc:
        raise ConflictException(
            code=refusal_code(exc, 'LEAVE_ORG_FAILED'), message=refusal_text(exc)
        ) from exc
    return MessageResponse(message='Left organization successfully')


@router.patch('/my/members/{user_id}/role', response_model=MemberRoleResponse)
async def change_member_role(
    user_id: UUID,
    data: MemberRoleUpdate,
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    """Change what a member of this organization is allowed to do. Admin only.

    Accepts either a built-in level (``role``) or an org-scoped custom role
    (``role_id``) — the schema enforces exactly one.
    """
    if not current_user.organization_id:
        raise NotFoundException('member', get_current_lang())

    member = await change_member_role_audited(
        db,
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        member_id=user_id,
        role=data.role,
        role_id=data.role_id,
    )

    return MemberRoleResponse(
        message='Member role updated',
        user_id=str(user_id),
        role=member.role,
        role_id=str(data.role_id) if data.role_id else None,
    )


@router.post('/my/remove-member/{user_id}', response_model=RemoveMemberResponse)
async def remove_member(
    user_id: UUID,
    current_user: UserContextDTO = Depends(get_current_admin_user),
    db=Depends(get_async_db, scope='function'),
):
    if user_id == current_user.id:
        raise catalogue_refusal('cannot_remove_yourself')

    if not current_user.organization_id:
        raise NotFoundException('member', get_current_lang())

    user_to_remove = await UserService.get_by_id_in_org_async(
        db, user_id, current_user.organization_id
    )
    if not user_to_remove:
        raise NotFoundException('member', get_current_lang())

    # Access changes are a first-order audit category, and this was the one
    # that wrote nothing: the invitation was logged, the role change was
    # logged, and the removal — the act somebody covering their tracks would
    # reach for — went unrecorded. Written in the removal's own transaction,
    # so the entry and the removal land together or not at all.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=AuditAction.SOFT_DELETE,
        target_type=AuditTargetType.ORG_MEMBER,
        target_id=user_id,
        snapshot={
            'name': user_to_remove.email,
            'before': {'organization': True, 'role': user_to_remove.role},
            'after': {'organization': False},
        },
    )
    await remove_member_service(db, user_to_remove)

    return RemoveMemberResponse(
        message='Member removed from organization', user_id=str(user_id)
    )
