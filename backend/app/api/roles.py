"""GET/POST /api/v1/roles + permission update + assignment.

Admin-only (SYSTEM_CONFIG_WRITE).
Org-scoped: a request can only see/mutate roles belonging to the
caller's organisation. System roles (organization_id IS NULL) are
read-only at the router layer -- their mutation belongs to a
deployment-level admin tool, not the in-app settings panel.

The ``require_permission(SystemPermission.SYSTEM_CONFIG_WRITE)`` guard
is applied per-endpoint because FastAPI does not allow parameter-less
dependency functions like ``require_permission(...)`` on a router's
``dependencies=[...]`` list at the time of writing (we use the same
pattern as ``_items_crud.py``).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    RoleDTO,
    RoleHolderDTO,
    UserContextDTO,
)
from app.core.contracts._system_dtos import SystemPermission
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_any_permission,
    require_org,
    require_permission,
)
from app.core.exceptions import ConflictException, RoleInUseError
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message
from app.schemas.pagination import PaginatedResponse

router = APIRouter(prefix='/roles')


class RoleCreate(BaseModel):
    """Request body for creating a new org-scoped role."""

    name: str = Field(min_length=1, max_length=100)
    permissions: list[str] = Field(default_factory=list)


class PermissionUpdate(BaseModel):
    """Request body for the permission-replace endpoint."""

    permissions: list[str] = Field(default_factory=list)


class RoleRename(BaseModel):
    """Request body for the rename endpoint."""

    name: str = Field(min_length=1, max_length=100)


async def _role_snapshot(db: AsyncSession, org_id: UUID, role_id: UUID) -> dict:
    """What a journal entry says a role was: its name and what it carried.

    Falls back to the id alone if the role is not this organization's — the
    act is refused a line later by the service, and a journal helper is not
    the place to decide that.
    """
    for role in await core_api.roles.list_for_org_async(db, org_id):
        if role.id == role_id:
            return {'name': role.name, 'permissions': list(role.permissions)}
    return {'name': str(role_id), 'permissions': []}


async def _journal(
    db: AsyncSession,
    actor: UserContextDTO,
    org_id: UUID,
    *,
    action: AuditAction,
    target_id: UUID,
    snapshot: dict,
    target_type: AuditTargetType = AuditTargetType.ROLE,
) -> None:
    """Record an act on the role catalogue in the organization's journal.

    `system:config:write` lets its holder write the catalogue and then assign
    themselves what they wrote; `docs/subsystems/ROLES.md` decides not to
    refuse that, and rests the decision on the act leaving a record. It used
    to leave one on stdout — nothing a reader of the organization's journal
    could ever see.
    """
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=actor.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        snapshot=snapshot,
    )


@router.get('', response_model=PaginatedResponse[RoleDTO])
async def list_roles(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.SYSTEM_CONFIG_WRITE),
):
    org_id = require_org(current_user)
    roles = await core_api.roles.list_for_org_async(db, org_id)
    return PaginatedResponse.from_full_list(roles, offset=offset, limit=limit)


@router.get('/permission-catalog')
async def permission_catalog(
    all_modules: bool = Query(
        False,
        description=(
            'Name the permissions of every installed module, not only those the '
            'organization runs. A screen that reads history (a key issued while '
            'a module was on) needs the label of a permission whatever the '
            "module's state is now; the roles matrix keeps the default."
        ),
    ),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_any_permission(
        SystemPermission.SYSTEM_CONFIG_WRITE, SystemPermission.ADMIN_ACCESS
    ),
) -> dict[str, object]:
    """Every permission a role may be granted, grouped for the RBAC matrix.

    Open to a holder of ``admin:access`` as well as of ``system:config:write``:
    the audit log, which that grant admits, names a key's permissions from this
    list, and a list of labels grants nothing.

    System permissions plus the ones declared by modules the caller's
    organization has enabled. The role editor needs this: a module permission
    that is never offered here cannot be granted, so the guard on the endpoint
    would reject everyone forever.

    Scoping to enabled modules is deliberate — a matrix column for a module the
    org does not run is a grant that can never take effect.
    """
    from app.api.modules import _resolve_modules
    from app.core._registry_class import module_registry

    if all_modules:
        return module_registry.get_permissions_catalog()
    enabled = await _resolve_modules(current_user, db)
    return module_registry.get_permissions_catalog(enabled)


@router.post('', response_model=RoleDTO, status_code=status.HTTP_201_CREATED)
async def create_role(
    data: RoleCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.SYSTEM_CONFIG_WRITE),
):
    org_id = require_org(current_user)
    role = await core_api.roles.create_async(
        db,
        organization_id=org_id,
        name=data.name,
        permissions=data.permissions,
    )
    await _journal(
        db,
        current_user,
        org_id,
        action=AuditAction.CREATE,
        target_id=role.id,
        snapshot={'name': role.name, 'permissions': list(role.permissions)},
    )
    return role


@router.put('/{role_id}/permissions', response_model=RoleDTO)
async def update_role_permissions(
    role_id: UUID,
    data: PermissionUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.SYSTEM_CONFIG_WRITE),
):
    org_id = require_org(current_user)
    before = await _role_snapshot(db, org_id, role_id)
    role = await core_api.roles.update_permissions_async(
        db,
        organization_id=org_id,
        role_id=role_id,
        permissions=data.permissions,
    )
    await _journal(
        db,
        current_user,
        org_id,
        action=AuditAction.UPDATE,
        target_id=role.id,
        snapshot={
            'name': role.name,
            'before': {'permissions': before['permissions']},
            'after': {'permissions': list(role.permissions)},
        },
    )
    return role


@router.post('/users/{user_id}/{role_id}')
async def assign_role_to_user(
    user_id: UUID,
    role_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.SYSTEM_CONFIG_WRITE),
):
    org_id = require_org(current_user)
    created = await core_api.roles.assign_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        role_id=role_id,
        actor_user_id=current_user.id,
    )
    if created:
        # Filed under the member, the way the other path that hands somebody a
        # custom role is (`PUT /organizations/my/members/{id}/role`): the
        # question the journal is opened with is who may do what, and the
        # answer is about a person. Flat, not before/after — the member did
        # not hold this role a moment ago, so there is no earlier value to
        # print, and a lone `after` reads as "—" in the Detail column. The
        # permissions travel with it because the role they name is editable
        # afterwards, and the entry has to keep saying what was handed over
        # on the day it was handed over.
        from app.services.user_service import UserService

        role = await _role_snapshot(db, org_id, role_id)
        member = await UserService.get_by_id_in_org_async(db, user_id, org_id)
        await _journal(
            db,
            current_user,
            org_id,
            action=AuditAction.UPDATE,
            target_id=user_id,
            target_type=AuditTargetType.ORG_MEMBER,
            snapshot={
                'name': member.email if member else str(user_id),
                # The name, not the id. The reading side resolves a `role_id`
                # against the roles that exist *now*, and a role can be
                # deleted — after which the entry recording who was given it
                # would read as eight characters of a dead id. The journal is
                # opened months later, and a row has to be legible without
                # opening the record it names.
                'role_name': role['name'],
                'permissions': role['permissions'],
            },
        )
    return {'created': created}


@router.patch('/{role_id}', response_model=RoleDTO)
async def rename_role(
    role_id: UUID,
    data: RoleRename,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.SYSTEM_CONFIG_WRITE),
):
    org_id = require_org(current_user)
    before = await _role_snapshot(db, org_id, role_id)
    role = await core_api.roles.rename_async(
        db, organization_id=org_id, role_id=role_id, name=data.name
    )
    await _journal(
        db,
        current_user,
        org_id,
        action=AuditAction.UPDATE,
        target_id=role.id,
        snapshot={
            'name': role.name,
            'before': {'name': before['name']},
            'after': {'name': role.name},
        },
    )
    return role


@router.get('/{role_id}/members', response_model=PaginatedResponse[RoleHolderDTO])
async def list_role_members(
    role_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.SYSTEM_CONFIG_WRITE),
):
    """Who holds this role — what the delete refusal is about."""
    org_id = require_org(current_user)
    holders = await core_api.roles.holders_async(
        db, organization_id=org_id, role_id=role_id
    )
    return PaginatedResponse.from_full_list(holders, offset=offset, limit=limit)


@router.delete('/{role_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.SYSTEM_CONFIG_WRITE),
) -> None:
    """Delete a role nobody holds.

    Refuses while somebody still does, and says how many. The association rows
    cascade, so a permissive delete would succeed quietly and drop each holder
    back to the level their ``User.role`` names — a promotion, for a role that
    narrowed access, that nothing afterwards would show.
    """
    org_id = require_org(current_user)
    try:
        # Read before the delete: the row is gone by the time the entry is
        # written, and an entry naming eight characters of a dead id is not a
        # record of anything.
        doomed = await _role_snapshot(db, org_id, role_id)
        await core_api.roles.delete_async(db, organization_id=org_id, role_id=role_id)
    except RoleInUseError as exc:
        raise ConflictException(
            'ROLE_IN_USE',
            get_error_message('role_in_use', get_current_lang()),
            details={'member_count': len(exc.holders)},
        ) from exc
    await _journal(
        db,
        current_user,
        org_id,
        action=AuditAction.HARD_DELETE,
        target_id=role_id,
        snapshot=doomed,
    )
