from uuid import UUID

import jwt
from fastapi import Depends, Request, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.audit_actor import set_api_key_actor
from app.core.contracts import (
    API_KEY_HEADER,
    API_KEY_PREFIX,
    OrganizationDTO,
    SystemPermission,
    UserContextDTO,
)
from app.core.datetimes import set_request_country
from app.core.exceptions import AppException, catalogue_status_refusal
from app.core.token_blacklist import token_blacklist
from app.database import get_async_db
from app.i18n.service import get_current_lang, get_error_message
from app.models.user import User
from app.services import permissions_service
from app.services._org_reads import DEFERRED_DTO_COLUMNS
from app.services.token_service import verify_token_async


class _SessionToken(OAuth2PasswordBearer):
    """The bearer token — unless the request carries an API key in its own header.

    A request that sends only ``X-API-Key`` has no bearer token, and the
    plain scheme would refuse it before the key is ever read.
    """

    async def __call__(self, request: Request) -> str | None:
        if request.headers.get(API_KEY_HEADER):
            return None
        return await super().__call__(request)


# The scheme keeps its published name: OpenAPI importers key on it.
oauth2_scheme = _SessionToken(
    tokenUrl='/api/v1/auth/login', scheme_name='OAuth2PasswordBearer'
)
api_key_header = APIKeyHeader(
    name=API_KEY_HEADER, scheme_name='ApiKey', auto_error=False
)

#: Where an API-key request's user carries the key's permission list.
_API_KEY_PERMISSIONS_ATTR = '_api_key_permissions'


async def resolve_notification_user(
    user_id: UUID | str,
) -> tuple[UUID | None, UUID | None, bool]:
    """Resolve a user's id, organization id, and blocked flag for the WebSocket.

    Opens a short-lived session — the WS endpoint must not hold a DB session
    for the whole connection lifetime. Returns ``(user_id, organization_id,
    is_blocked)``. ``user_id`` is None when the user does not exist or is
    inactive (callers must refuse the connection in that case). The
    organization is taken from the user record, never from a client-supplied
    value. ``is_blocked`` is reported separately so the WS handler can
    refuse a blocked-but-active user with a distinct close code.
    """
    from app.database import AsyncSessionLocal

    if AsyncSessionLocal is None:
        return None, None, False
    async with AsyncSessionLocal() as session:
        user = await session.get(User, UUID(str(user_id)))
    if user is None or not user.is_active:
        return None, None, False
    return user.id, user.organization_id, user.is_blocked


def _note_request_country(user: User) -> None:
    """Let a printed date follow the acting organization's country.

    The organization is loaded with the user (``selectin``), so this costs no
    query.
    """
    set_request_country(user.organization.country if user.organization else None)


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    api_key: str | None = Depends(api_key_header),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> User:
    """
    Fetch the currently logged in user based on the JWT token or an API key.

    A key travels in its own header. Sent as ``Authorization: Bearer`` it is
    still honoured for one minor release — the response then carries a
    ``Deprecation`` header (``app._middleware``) — and recognised there by its
    prefix, the only way to tell it from a JWT in that header.
    """
    lang = get_current_lang()
    # Without the key's own header the scheme has already refused a request
    # carrying no bearer token, so ``token`` is a string from here on.
    credential = api_key or token or ''

    # --- API Key flow ---
    if api_key or credential.startswith(API_KEY_PREFIX):
        from app.core.api_key_auth import api_key_scopes_admit, resolve_api_key

        identity = await resolve_api_key(db, credential)
        if identity is None:
            raise AppException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                code='INVALID_API_KEY',
                message=get_error_message('invalid_api_key', lang),
                headers={'WWW-Authenticate': 'Bearer'},
            )
        # A key issued for one job (a print agent, say) reaches only the
        # endpoints that guard its scopes' permissions — refused here, before
        # any route runs, because most reads ask for no permission at all.
        if identity.scopes and not api_key_scopes_admit(
            identity.scopes, request.scope.get('route')
        ):
            raise AppException(
                status_code=status.HTTP_403_FORBIDDEN,
                code='API_KEY_SCOPE_REFUSED',
                message=get_error_message(
                    'api_key_scope_refused', lang, scope=', '.join(identity.scopes)
                ),
            )
        user = await db.get(User, identity.user_id)
        if not user or not user.is_active:
            raise AppException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                code='API_KEY_OWNER_INACTIVE',
                message=get_error_message('api_key_owner_inactive', lang),
                headers={'WWW-Authenticate': 'Bearer'},
            )
        # A blocked account keeps no credentials, machine ones included: the
        # JWT path refuses it, so leaving API keys alive would make blocking a
        # compromised account a partial measure.
        if user.is_blocked:
            raise catalogue_status_refusal(
                'user_blocked',
                status.HTTP_403_FORBIDDEN,
                reason=user.blocking_reason
                or get_error_message('user_blocked_no_reason', lang),
            )
        # Enforce user-level revocation even for API keys: an admin who
        # revokes a user's token family (e.g. on compromise) must also block
        # API-key-authenticated requests, not only JWT ones.
        if await token_blacklist.is_user_revoked(str(user.id)):
            raise catalogue_status_refusal(
                'token_invalid',
                status.HTTP_401_UNAUTHORIZED,
                headers={'WWW-Authenticate': 'Bearer'},
            )
        # Hand get_current_user_context what the key may do: the request acts
        # with the key's own list, not its owner's. Not a mapped column, so it
        # goes on the instance itself and dies with the request's session.
        vars(user)[_API_KEY_PERMISSIONS_ATTR] = identity.permissions
        # And name the credential to the journal: an entry written through
        # this request is the key's work, not its owner's, and once the key is
        # revoked this prefix is the only thing that still ties the two.
        set_api_key_actor(identity.key_prefix)
        _note_request_country(user)
        return user

    # --- Standard JWT flow ---
    if await token_blacklist.is_revoked(credential):
        raise catalogue_status_refusal(
            'token_invalid',
            status.HTTP_401_UNAUTHORIZED,
            headers={'WWW-Authenticate': 'Bearer'},
        )
    user = await verify_token_async(credential, db)
    _note_request_country(user)
    return user


async def user_from_refresh_cookie(
    db: AsyncSession, refresh_token: str | None
) -> User | None:
    """Resolve a user from the HttpOnly refresh_token cookie (read-only).

    Browser-native requests (``<img>``, attachment download) cannot carry the
    in-memory access token's ``Authorization: Bearer`` header. They do send the
    refresh cookie, so media serving accepts it as a CDN-signed-cookie-
    equivalent. This NEVER rotates or reissues tokens (unlike /auth/refresh) —
    it only verifies the cookie to establish identity.

    Returns None if the cookie is absent, malformed, expired, revoked, or the
    user is inactive.

    Unlike the ``/auth/refresh`` endpoint (which decodes with
    ``verify_exp=False`` so it can read claims of a just-expired token before
    rotating it), this function *authenticates* the request — so it MUST
    honour ``exp``. An expired refresh cookie must not authenticate ``/uploads``
    requests; otherwise a stale cookie acts as a perpetual bearer token for
    media serving.
    """
    if not refresh_token:
        return None
    try:
        payload = jwt.decode(
            refresh_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={'verify_exp': True},
        )
    except jwt.ExpiredSignatureError:
        # Expired refresh cookie must not authenticate media requests.
        return None
    except jwt.PyJWTError:
        return None
    user_id = payload.get('sub')
    session_id = payload.get('sid', user_id or '')
    if not user_id:
        return None
    # Only a refresh token belongs in this cookie.
    if payload.get('type') != 'refresh':
        return None
    # Honour revocation (logout, token-family revoke) exactly like the bearer flow.
    if await token_blacklist.is_revoked(refresh_token):
        return None
    if await token_blacklist.is_user_revoked(user_id, session_id):
        return None
    # The cookie must also die when the password changed after it was
    # issued — otherwise a stolen cookie keeps serving media for 30 days.
    if await token_blacklist.is_issued_before_credential_change(
        user_id, payload.get('iat')
    ):
        return None
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


async def _load_organization_dto(
    db: AsyncSession, current_user: User
) -> OrganizationDTO | None:
    organization = current_user.organization
    if organization is None:
        return None
    await db.refresh(organization, list(DEFERRED_DTO_COLUMNS))
    return OrganizationDTO.model_validate(organization)


async def _load_user_context(db: AsyncSession, current_user: User) -> UserContextDTO:
    key_permissions: frozenset[str] | None = getattr(
        current_user, _API_KEY_PERMISSIONS_ATTR, None
    )
    organization = await _load_organization_dto(db, current_user)

    if key_permissions is not None:
        # The key's own list, chosen from its creator's permissions when it
        # was issued — nothing of its owner's current grants.
        #
        # What keeps a key out of administration is that no list can hold
        # `API_KEY_WITHHELD_PERMISSIONS`: every route asking for
        # `org:settings:write` refuses a key — the AI connections, the
        # equipment document templates, the SKU schema and the API key
        # register — including the one somebody adds next month without
        # reading this. Approvals, webhooks, invites and module toggles
        # resolve the same way or through `get_current_admin_user`; the role
        # is 'api_key', never 'admin', so the admin bypass in
        # `has_permission` does not apply. The API key register keeps three
        # explicit refusals of its own on top — a second lock on the door
        # that issues the keys.
        system_perm_map = {p.value: p for p in SystemPermission}
        return UserContextDTO(
            id=current_user.id,
            organization_id=current_user.organization_id,
            organization=organization,
            role='api_key',
            email=current_user.email,
            permissions={
                system_perm_map[p] for p in key_permissions if p in system_perm_map
            },
            extra_permissions={p for p in key_permissions if p not in system_perm_map},
        )

    # One resolution, shared with the fresh lookup modules make about
    # somebody who is not on the request: role rows when there are any, the
    # built-in level otherwise. Resolving it here as well is how the two
    # answers drifted apart the last time.
    perm_strings = await permissions_service.resolve_permission_strings_async(
        db,
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        base_role=current_user.role,
    )

    system_perm_map = {p.value: p for p in SystemPermission}
    permissions = set()
    extra_permissions: set[str] = set()
    for perm_str in perm_strings:
        if perm_str in system_perm_map:
            permissions.add(system_perm_map[perm_str])
        else:
            extra_permissions.add(perm_str)

    return UserContextDTO(
        id=current_user.id,
        organization_id=current_user.organization_id,
        organization=OrganizationDTO.model_validate(current_user.organization)
        if current_user.organization
        else None,
        role=current_user.role,
        email=current_user.email,
        is_superuser=getattr(current_user, 'is_superuser', False),
        permissions=permissions,
        extra_permissions=extra_permissions,
    )


async def get_current_user_context(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> UserContextDTO:
    """Return a lightweight user context for module-facing endpoints.

    Loads permissions from DB roles assigned to the user.  Falls back to the
    legacy role-string mapping if the user has no DB roles assigned (e.g.
    during gradual migration or in test environments that seed users without
    roles).

    When the user authenticated via an API key, the role is overridden to
    'api_key' and the permissions are the key's own list.
    """
    return await _load_user_context(db, current_user)
