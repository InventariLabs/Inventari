"""API Keys module router."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_key_auth import api_key_scopes
from app.core.contracts import (
    API_KEY_DEFAULT_PERMISSIONS,
    API_KEY_HEADER,
    API_KEY_WITHHELD_PERMISSIONS,
    AuditAction,
    AuditTargetType,
    SystemPermission,
    UserContextDTO,
)
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import catalogue_status_refusal, map_service_errors
from app.core.module_sdk import PaginatedResponse
from app.core.modules import require_module
from app.core.public_api import core_api
from app.modules.api_keys import schemas
from app.modules.api_keys.api_key_service import (
    create_api_key_async,
    list_api_keys,
    permission_catalog_async,
    resolve_key_permissions,
    revoke_api_key,
)

# Issuing a key and reading the list of issued keys are the same authority.
# They were not the same gate: creating and revoking asked for
# `org:settings:write`, listing asked only for `org:read`, which every member
# has — so any member could enumerate the organization's keys by name, prefix,
# issuer and last use. Declared on the router so the pair cannot drift apart
# again, and so an endpoint added later arrives closed.
#
# The same dependency closes `GET /api-keys/capabilities` to a key: a key can
# never hold `org:settings:write` (it is withheld), so it cannot read what a
# key may carry. Deliberate, and nothing consumes the endpoint as a key — it
# feeds the issuing form a signed-in administrator sees.
router = APIRouter(
    tags=['api-keys'],
    dependencies=[
        Depends(require_module('api_keys')),
        require_permission(SystemPermission.ORG_SETTINGS_WRITE),
    ],
)


def _row_id(value: object) -> UUID:
    """The id of an ``ApiKey`` row, as a UUID.

    The model predates ``Mapped[...]`` annotations, so its columns type as
    ``Column[UUID]`` even though every instance carries a real UUID.
    """
    return cast(UUID, value)


async def _grantable_async(
    db: AsyncSession, org_id: UUID, current_user: UserContextDTO
) -> tuple[list[dict[str, object]], list[str]]:
    """The organization's permission catalogue, and what the caller may grant.

    A key is issued from what its creator holds: whatever they could do
    themselves, and nothing more, minus what no key carries.
    """
    catalog = await permission_catalog_async(db, org_id)
    withheld = {p.value for p in API_KEY_WITHHELD_PERMISSIONS}
    grantable = [
        str(entry['key'])
        for entry in catalog
        if entry['key'] not in withheld
        and current_user.has_permission(str(entry['key']))
    ]
    return catalog, grantable


@router.get('/capabilities', response_model=schemas.ApiKeyCapabilities)
async def get_capabilities(
    current_user: UserContextDTO = Depends(get_current_user_context),
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> schemas.ApiKeyCapabilities:
    """What a key issued here may carry, and the header that carries it."""
    catalog, grantable = await _grantable_async(db, org_id, current_user)
    return schemas.ApiKeyCapabilities.model_validate(
        {
            'catalog': catalog,
            'grantable': grantable,
            'default_permissions': sorted(p.value for p in API_KEY_DEFAULT_PERMISSIONS),
            'withheld_permissions': sorted(
                p.value for p in API_KEY_WITHHELD_PERMISSIONS
            ),
            'admin_areas_blocked': True,
            'header': API_KEY_HEADER,
            'scopes': [
                {'name': name, 'permissions': list(permissions)}
                for name, permissions in api_key_scopes().items()
            ],
        }
    )


@router.get('', response_model=PaginatedResponse[schemas.ApiKeyResponse])
async def list_keys(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> PaginatedResponse[schemas.ApiKeyResponse]:
    # API keys themselves cannot manage API keys
    if current_user.role == 'api_key':
        raise catalogue_status_refusal(
            'api_key_cannot_manage', status.HTTP_403_FORBIDDEN
        )
    keys, total = await list_api_keys(db, org_id, offset=offset, limit=limit)
    return PaginatedResponse.from_slice(
        [schemas.ApiKeyResponse.from_orm_with_email(k) for k in keys],
        offset,
        limit,
        total,
    )


@router.post('', response_model=schemas.ApiKeyCreatedResponse, status_code=201)
async def create_key(
    payload: schemas.ApiKeyCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> schemas.ApiKeyCreatedResponse:
    # API keys themselves cannot create new API keys
    if current_user.role == 'api_key':
        raise catalogue_status_refusal(
            'api_key_cannot_create', status.HTTP_403_FORBIDDEN
        )
    _, grantable = await _grantable_async(db, org_id, current_user)
    permissions = resolve_key_permissions(
        grantable=grantable, permissions=payload.permissions, scopes=payload.scopes
    )
    api_key, raw_key = await create_api_key_async(
        db=db,
        organization_id=org_id,
        user_id=current_user.id,
        name=payload.name,
        permissions=permissions,
        expires_at=payload.expires_at,
        scopes=payload.scopes,
    )
    # Issuing a credential is an administrative act and left no trace at all
    #: after a session that created two keys and revoked one, the log
    # held a single entry, for a product.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=current_user.id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.API_KEY,
        target_id=_row_id(api_key.id),
        snapshot={
            'name': api_key.name,
            'key_prefix': api_key.key_prefix,
            'permissions': api_key.permissions,
            'scopes': api_key.scope_names,
        },
    )
    return schemas.ApiKeyCreatedResponse.model_validate(
        {
            'id': api_key.id,
            'name': api_key.name,
            'key_prefix': api_key.key_prefix,
            'raw_key': raw_key,
            'expires_at': api_key.expires_at,
            'created_at': api_key.created_at,
            'permissions': api_key.permissions,
            'scopes': api_key.scope_names,
        }
    )


@router.delete('/{key_id}', status_code=204)
@map_service_errors
async def revoke_key(
    key_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    if current_user.role == 'api_key':
        raise catalogue_status_refusal(
            'api_key_cannot_revoke', status.HTTP_403_FORBIDDEN
        )
    api_key = await revoke_api_key(db, org_id, key_id)
    # The row leaves the list on revocation, so "who revoked this key" had no
    # answer on any screen. This entry is it.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=current_user.id,
        action=AuditAction.SOFT_DELETE,
        target_type=AuditTargetType.API_KEY,
        target_id=_row_id(api_key.id),
        snapshot={'name': api_key.name, 'key_prefix': api_key.key_prefix},
    )
