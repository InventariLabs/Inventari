"""DB-backed permission and role queries.

These functions complement the cached ``UserContextDTO.has_permission``
path (used by ``deps.require_permission``) with a fresh DB lookup for
admin tooling and post-mutation checks where the cached context would
be stale.

``resolve_permission_strings_async`` is where the two paths meet: the
session context built at the door resolves through it, and so does the
fresh lookup a caller makes about somebody who is not on the request.
They used to resolve separately and disagreed — the fresh one read
``roles`` rows only, so a member holding a permission by their built-in
level alone read as holding nothing.

Used by ``core_api.permissions`` and ``core_api.roles`` facades.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import SystemPermission
from app.core.exceptions import RoleInUseError, ServiceRejectionError
from app.core.logging import get_logger
from app.models.role import Role, UserRole
from app.models.user import User
from app.services.builtin_roles import BUILTIN_ROLES, builtin_role_permissions

logger = get_logger(__name__)


def _perm_to_str(permission: SystemPermission | str) -> str:
    """Normalise a permission (enum or string) to its canonical string."""
    if isinstance(permission, SystemPermission):
        return permission.value
    return str(permission)


async def resolve_permission_strings_async(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    base_role: str,
) -> set[str]:
    """Every permission key this user holds in this organization.

    Custom role rows, when the user has any, are the whole answer: assigning
    one is a deliberate narrowing, and falling back to the level underneath
    would undo it. With no row, the built-in level decides — which is where
    the module manifests' ``default_roles`` land, so a manager holds
    ``approvals:read`` in an organization that never created a role.

    Roles are scoped to the organization on purpose: ``user_roles`` carries
    no organization of its own, so filtering on the user alone would hand a
    member of several the union of their grants everywhere.
    """
    result = await db.execute(
        select(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user_id,
            Role.organization_id == organization_id,
        )
    )
    db_roles = result.scalars().all()
    if db_roles:
        return {
            perm
            for role in db_roles
            if isinstance(role.permissions, list)
            for perm in role.permissions
        }
    return builtin_role_permissions(base_role)


async def check_user_permission_async(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    permission: SystemPermission | str,
) -> bool:
    """Return True iff the user holds *permission* **in this organization**.

    Queries the DB fresh (does not consult the cached context), and answers
    what ``UserContextDTO.has_permission`` would: the administrator bypass
    first, then the same resolution of role rows and built-in level. A caller
    asking about somebody other than the requester — a workflow gate checking
    whether its named approvers can decide — has to get the answer the guards
    will give that person, not a narrower one.

    Returns False for a user who is not a member of this organization.
    """
    user = await db.get(User, user_id)
    if user is None or user.organization_id != organization_id:
        return False
    if user.role == 'admin':
        return True

    held = await resolve_permission_strings_async(
        db,
        user_id=user_id,
        organization_id=organization_id,
        base_role=user.role,
    )
    return _perm_to_str(permission) in held


async def has_holder_async(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    permission: SystemPermission | str,
) -> bool:
    """Whether anybody in this organization holds *permission*.

    The question behind "is there a stage open to nobody?" — an organization
    that has never granted the approve right anywhere. It is answered from
    the same three sources ``check_user_permission_async`` resolves for one
    person, and in the same order: an administrator (who holds everything),
    a custom role row (which is the whole answer for its holders, level
    included), and the built-in level for everybody else. An account that is
    switched off holds nothing: it cannot sign in, so it cannot decide.

    Three queries, whatever the size of the organization: the levels' member
    counts are not what decides here, so a level that grants the permission
    only counts when somebody actually resolves by it.
    """
    perm = _perm_to_str(permission)

    admin = await db.scalar(
        select(User.id)
        .where(
            User.organization_id == organization_id,
            User.is_active.is_(True),
            User.role == 'admin',
        )
        .limit(1)
    )
    if admin is not None:
        return True

    granted_role_holder = await db.scalar(
        select(UserRole.user_id)
        .join(Role, Role.id == UserRole.role_id)
        .join(User, User.id == UserRole.user_id)
        .where(
            User.organization_id == organization_id,
            User.is_active.is_(True),
            Role.organization_id == organization_id,
            Role.permissions.contains([perm]),
        )
        .limit(1)
    )
    if granted_role_holder is not None:
        return True

    # Everybody else resolves by their level, and only by it: a person
    # holding a role row was answered above, where a level that grants the
    # permission does not undo the row.
    granting_levels = [
        level for level in BUILTIN_ROLES if perm in builtin_role_permissions(level)
    ]
    if not granting_levels:
        return False
    rowless = await db.scalar(
        select(User.id)
        .outerjoin(UserRole, UserRole.user_id == User.id)
        .where(
            User.organization_id == organization_id,
            User.is_active.is_(True),
            User.role.in_(granting_levels),
            UserRole.user_id.is_(None),
        )
        .limit(1)
    )
    return rowless is not None


async def holders_of_permission_async(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    permission: SystemPermission | str,
) -> set[uuid.UUID]:
    """Everybody in this organization who currently holds *permission*.

    The set form of ``has_holder_async``, resolved from the same three
    sources in the same shape: the administrator bypass (an admin holds
    everything), a custom role row (the whole answer for its holders, level
    included), and the built-in level for everybody without a row. A queue
    asking "is the requester the ONLY one who could decide?" needs the set,
    not the boolean. Accounts that are switched off are not in it.
    """
    perm = _perm_to_str(permission)
    holders: set[uuid.UUID] = set()

    admins = await db.scalars(
        select(User.id).where(
            User.organization_id == organization_id,
            User.is_active.is_(True),
            User.role == 'admin',
        )
    )
    holders.update(admins.all())

    granted_role_holders = await db.scalars(
        select(UserRole.user_id)
        .join(Role, Role.id == UserRole.role_id)
        .join(User, User.id == UserRole.user_id)
        .where(
            User.organization_id == organization_id,
            User.is_active.is_(True),
            Role.organization_id == organization_id,
            Role.permissions.contains([perm]),
        )
    )
    holders.update(granted_role_holders.all())

    granting_levels = [
        level for level in BUILTIN_ROLES if perm in builtin_role_permissions(level)
    ]
    if granting_levels:
        rowless = await db.scalars(
            select(User.id)
            .outerjoin(UserRole, UserRole.user_id == User.id)
            .where(
                User.organization_id == organization_id,
                User.is_active.is_(True),
                User.role.in_(granting_levels),
                UserRole.user_id.is_(None),
            )
        )
        holders.update(rowless.all())

    return holders


#: The keys that make their holder an administrator of the organization:
#: ``admin:access`` is what ``get_current_admin_user`` admits, and
#: ``system:config:write`` lets its holder grant themselves that key at will
#: (docs/subsystems/ROLES.md), so it is the same authority under another name.
ADMINISTRATION_PERMISSIONS: tuple[SystemPermission, ...] = (
    SystemPermission.ADMIN_ACCESS,
    SystemPermission.SYSTEM_CONFIG_WRITE,
)


async def administrators_async(
    db: AsyncSession, *, organization_id: uuid.UUID
) -> set[uuid.UUID]:
    """Everybody who administers this organization, by any of the two keys.

    The built-in level, and a custom role carrying either key of
    ``ADMINISTRATION_PERMISSIONS``. The question a notice "for the
    administrators" asks: it used to be answered with ``role == 'admin'``
    alone, so an organization that built its own administration role instead
    of handing out the built-in level got no warnings at all. Accounts that
    are switched off are not in it.
    """
    administrators: set[uuid.UUID] = set()
    for permission in ADMINISTRATION_PERMISSIONS:
        administrators |= await holders_of_permission_async(
            db, organization_id=organization_id, permission=permission
        )
    return administrators


async def permissions_for_users_async(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, set[str]]:
    """Every permission each of these people holds, in two queries.

    The batch twin of ``resolve_permission_strings_async``, for callers
    asking about a list of people rather than one — a queue that has to say,
    per request, whether the stage it waits at can be decided at all. Same
    rules, same answer per person: the administrator bypass, a custom role
    row as the whole answer, the built-in level otherwise. People who are not
    members of this organization, or whose account is switched off, are
    absent from the result.
    """
    wanted = list(dict.fromkeys(user_ids))
    if not wanted:
        return {}

    users = (
        await db.execute(
            select(User).where(
                User.id.in_(wanted),
                User.organization_id == organization_id,
                User.is_active.is_(True),
            )
        )
    ).scalars()
    by_id = {user.id: user for user in users}
    if not by_id:
        return {}

    rows = await db.execute(
        select(UserRole.user_id, Role)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            UserRole.user_id.in_(list(by_id)),
            Role.organization_id == organization_id,
        )
    )
    granted: dict[uuid.UUID, set[str]] = {}
    for user_id, role in rows.all():
        permissions = role.permissions if isinstance(role.permissions, list) else []
        granted.setdefault(user_id, set()).update(permissions)

    held: dict[uuid.UUID, set[str]] = {}
    for user_id, user in by_id.items():
        if user.role == 'admin':
            held[user_id] = builtin_role_permissions('admin')
        elif user_id in granted:
            held[user_id] = granted[user_id]
        else:
            held[user_id] = builtin_role_permissions(user.role)
    return held


async def list_roles_for_user_async(
    db: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[Role]:
    """Return the roles this user holds in this organisation.

    A member of several organisations holds a role in the one it was granted
    in and nowhere else — ``user_roles`` carries no organisation of its own,
    so the role's is what scopes the answer.
    """
    stmt = (
        select(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
        .where(Role.organization_id == organization_id)
        .order_by(Role.is_system.desc(), Role.name.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def assign_role_async(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> bool:
    """Link a user to a role. Idempotent: returns True if newly created,
    False if link already existed.

    Raises ``ValueError`` if the role does not exist, if the role belongs
    to a different organization, or if the *target user* does not belong to
    *organization_id* (the role was checked, the recipient was not —
    so an admin could grant a role to a member of another organization).
    """
    role = await db.get(Role, role_id)
    if role is None:
        raise ServiceRejectionError('role_not_found')
    if role.organization_id != organization_id:
        raise ServiceRejectionError('role_other_organization')

    target = await db.get(User, user_id)
    if target is None or target.organization_id != organization_id:
        raise ServiceRejectionError('user_not_in_organization')

    existing = await db.execute(
        select(UserRole)
        .where(UserRole.user_id == user_id)
        .where(UserRole.role_id == role_id)
    )
    if existing.scalar_one_or_none() is not None:
        logger.info(
            'Role assign no-op (already linked): user=%s role=%s actor=%s',
            user_id,
            role_id,
            actor_user_id,
        )
        return False

    db.add(UserRole(user_id=user_id, role_id=role_id))
    await db.flush()
    logger.info(
        'Role assigned: user=%s role=%s org=%s actor=%s',
        user_id,
        role_id,
        organization_id,
        actor_user_id,
    )
    return True


async def org_role_map_async(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_ids: list[uuid.UUID],
) -> dict[uuid.UUID, Role]:
    """The org-scoped custom role each given user holds, keyed by user id.

    One role per person is the convention the member UI assumes; legacy data
    may link more than one, so the alphabetically first role wins to keep the
    member list deterministic. System roles (``organization_id IS NULL``) are
    not custom roles and are excluded.
    """
    if not user_ids:
        return {}
    stmt = (
        select(UserRole.user_id, Role)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id.in_(user_ids))
        .where(Role.organization_id == organization_id)
        .order_by(Role.name.asc())
    )
    result = await db.execute(stmt)
    out: dict[uuid.UUID, Role] = {}
    for user_id, role in result.all():
        out.setdefault(user_id, role)
    return out


async def list_roles_for_org_async(
    db: AsyncSession,
    organization_id: uuid.UUID,
) -> list[Role]:
    """Return the roles this organisation has of its own.

    The four built-in levels are not among them and never were rows: the
    caller in ``core.public_api.roles`` puts them in front of this list.
    """
    stmt = (
        select(Role)
        .where(Role.organization_id == organization_id)
        .order_by(Role.is_system.desc(), Role.name.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_role_async(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    name: str,
    permissions: list[str],
) -> Role:
    """Create a new organisation-scoped role.

    Permissions is a list of canonical permission strings
    (SystemPermission enum values or module-registered permission
    strings). Caller is responsible for validating that the
    permission strings are recognised -- we accept any string here
    so module-registered permissions round-trip cleanly.

    Raises ``ServiceRejectionError('role_name_taken')`` when a role with the
    same name already exists in the organisation (case-insensitive
    comparison) — the 400 handler speaks the key in the request language.
    """
    existing = (
        await db.execute(
            select(Role).where(
                (Role.organization_id == organization_id)
                & (func.lower(Role.name) == func.lower(name))
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ServiceRejectionError('role_name_taken', name=name)

    role = Role(
        organization_id=organization_id,
        name=name,
        permissions=list(permissions),
        is_system=False,
    )
    db.add(role)
    await db.flush()
    await db.refresh(role)
    logger.info(
        'Role created: name=%s org=%s perms=%d',
        name,
        organization_id,
        len(permissions),
    )
    return role


async def update_role_permissions_async(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    role_id: uuid.UUID,
    permissions: list[str],
) -> Role:
    """Replace the permission set on an existing role.

    Org-scoping guard: refuses to mutate a role that belongs to a different
    organisation. The case this used to guard on top of that — a role
    belonging to none, and therefore to all — is now refused by the column.
    """
    role = await db.get(Role, role_id)
    if role is None:
        raise ServiceRejectionError('role_not_found')
    if role.organization_id != organization_id:
        raise ServiceRejectionError('role_other_organization')

    role.permissions = list(permissions)
    db.add(role)
    await db.flush()
    await db.refresh(role)
    logger.info(
        'Role permissions updated: role=%s org=%s perms=%d',
        role_id,
        organization_id,
        len(permissions),
    )
    return role


async def _org_role_or_error(
    db: AsyncSession, *, organization_id: uuid.UUID, role_id: uuid.UUID
) -> Role:
    """Fetch a role this organisation is allowed to mutate.

    The same guard ``update_role_permissions_async`` applies.
    """
    role = await db.get(Role, role_id)
    if role is None:
        raise ServiceRejectionError('role_not_found')
    if role.organization_id != organization_id:
        raise ServiceRejectionError('role_other_organization')
    return role


async def rename_role_async(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    role_id: uuid.UUID,
    name: str,
) -> Role:
    """Give an existing org role a new name, unique within the organisation.

    Raises ``ServiceRejectionError('role_name_taken')`` when another role
    already answers to the new name (case-insensitive).
    """
    role = await _org_role_or_error(
        db, organization_id=organization_id, role_id=role_id
    )
    clash = (
        await db.execute(
            select(Role).where(
                (Role.organization_id == organization_id)
                & (func.lower(Role.name) == func.lower(name))
                & (Role.id != role_id)
            )
        )
    ).scalar_one_or_none()
    if clash is not None:
        raise ServiceRejectionError('role_name_taken', name=name)

    role.name = name
    db.add(role)
    await db.flush()
    await db.refresh(role)
    logger.info('Role renamed: id=%s org=%s', role_id, organization_id)
    return role


async def role_holders_async(
    db: AsyncSession, *, organization_id: uuid.UUID, role_id: uuid.UUID
) -> list[User]:
    """Everyone in this organisation who currently holds the role."""
    await _org_role_or_error(db, organization_id=organization_id, role_id=role_id)
    result = await db.execute(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role_id == role_id, User.organization_id == organization_id)
        .order_by(User.email)
    )
    return list(result.scalars())


async def role_member_counts_async(
    db: AsyncSession, *, organization_id: uuid.UUID
) -> dict[uuid.UUID, int]:
    """How many people hold each role in this organisation, keyed by role id.

    One query for the whole list: the roles screen shows the number on every
    row, and a count per row would be a query per row.
    """
    result = await db.execute(
        select(UserRole.role_id, func.count(UserRole.user_id))
        .join(User, User.id == UserRole.user_id)
        .where(User.organization_id == organization_id)
        .group_by(UserRole.role_id)
    )
    return dict(result.all())  # type: ignore[arg-type]


async def builtin_role_member_counts_async(
    db: AsyncSession, *, organization_id: uuid.UUID
) -> dict[str, int]:
    """How many people this organisation has at each built-in level.

    Read off ``User.role``, because that is where a built-in level lives —
    there is no row in ``roles`` to count holders of.
    """
    result = await db.execute(
        select(User.role, func.count(User.id))
        .where(User.organization_id == organization_id)
        .group_by(User.role)
    )
    return {row[0]: row[1] for row in result.all()}


async def delete_role_async(
    db: AsyncSession, *, organization_id: uuid.UUID, role_id: uuid.UUID
) -> None:
    """Delete an org role that nobody holds.

    Refuses while somebody still holds it, and the refusal is the point. The
    association rows cascade, so a permissive delete would succeed silently and
    drop each holder back to the built-in level their ``User.role`` names —
    which for a role that *narrows* access is a promotion nobody asked for, and
    invisible afterwards. Reassigning the people first makes that a decision.
    """
    role = await _org_role_or_error(
        db, organization_id=organization_id, role_id=role_id
    )
    holders = await role_holders_async(
        db, organization_id=organization_id, role_id=role_id
    )
    if holders:
        raise RoleInUseError(role.name, holders=[u.id for u in holders])

    await db.delete(role)
    await db.flush()
    logger.info('Role deleted: id=%s org=%s', role_id, organization_id)
