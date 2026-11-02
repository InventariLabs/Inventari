"""
Module-safe role listing and assignment.

Modules should not query ``Role`` / ``UserRole`` directly — use this
facade so the join logic and org-scoping guard stay in one place.
"""

from __future__ import annotations

from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import RoleDTO, RoleHolderDTO
from app.core.logging import get_logger
from app.services import permissions_service
from app.services.builtin_roles import BUILTIN_ROLES, builtin_role_permissions

logger = get_logger(__name__)

#: Fixed namespace for the derived ids of the built-in levels. Any constant
#: UUID would do; it must simply never change, or every key and cache entry
#: on the roles screen moves under the reader.
BUILTIN_ROLE_NAMESPACE = UUID('0f1c4d2e-6b8a-4a1e-9c33-2f6f1a7d5b40')


class CoreRolesAPI:
    """Public Core API for module-safe role queries."""

    async def check_user_permission_async(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        organization_id: UUID,
        permission: str,
    ) -> bool:
        """Fresh DB lookup: does *user_id* hold *permission* in this org?

        Complements the cached ``UserContextDTO.has_permission`` path for
        callers that reason about a user who is not the one on the request —
        e.g. a workflow gate asking whether its named approvers can decide.
        """
        return await permissions_service.check_user_permission_async(
            db,
            user_id=user_id,
            organization_id=organization_id,
            permission=permission,
        )

    async def list_for_user_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        user_id: UUID,
    ) -> list[RoleDTO]:
        """Return the roles this user holds in the given org.

        A role belongs to one organisation, so a member of several holds it
        in that one and nowhere else.
        """
        roles = await permissions_service.list_roles_for_user_async(
            db, organization_id, user_id
        )
        return [RoleDTO.model_validate(r) for r in roles]

    async def role_ids_for_user_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        user_id: UUID,
    ) -> set[UUID]:
        """Every role this user holds here, the built-in level included.

        The ids are the ones ``list_for_org_async`` lists, so a module that
        stored a choice made on that list can ask whether somebody holds it.
        The level lives on ``User.role`` rather than in a row, and its id is
        derived from its name — here, in the one place that derives it.
        Empty for somebody outside the organization.
        """
        from .users import CoreUsersAPI

        user = await CoreUsersAPI().get_async(db, organization_id, user_id)
        if user is None:
            return set()
        custom = await permissions_service.list_roles_for_user_async(
            db, organization_id, user_id
        )
        return {uuid5(BUILTIN_ROLE_NAMESPACE, user.role)} | {r.id for r in custom}

    async def has_holder_async(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        permission: str,
    ) -> bool:
        """Whether anybody in this organisation holds *permission*.

        A different question from counting roles: this answers "could a stage
        open to anyone with the grant ever be decided here?", resolved the
        way the guards resolve it for a person — the administrator bypass, a
        custom role row, the built-in level.
        """
        return await permissions_service.has_holder_async(
            db, organization_id=organization_id, permission=permission
        )

    async def holders_of_permission_async(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        permission: str,
    ) -> set[UUID]:
        """Everybody in this organisation who currently holds *permission*.

        The set form of ``has_holder_async`` — a queue asking "is the
        requester the ONLY one who could decide this?" needs the holders,
        not the boolean.
        """
        return await permissions_service.holders_of_permission_async(
            db, organization_id=organization_id, permission=permission
        )

    async def administrators_async(
        self, db: AsyncSession, *, organization_id: UUID
    ) -> set[UUID]:
        """Everybody who administers this organisation, by authority.

        The built-in level and any custom role carrying an administration
        key; switched-off accounts are not in it. The recipients of a notice
        "for the administrators" a module sends without
        ``notify_org_admins_async``.
        """
        return await permissions_service.administrators_async(
            db, organization_id=organization_id
        )

    async def permissions_for_users_async(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        user_ids: list[UUID],
    ) -> dict[UUID, set[str]]:
        """Every permission each of these people holds, in two queries.

        The batch twin of ``check_user_permission_async``, for screens that
        ask about a list of people at once. Ids outside this organisation are
        absent from the result.
        """
        return await permissions_service.permissions_for_users_async(
            db, organization_id=organization_id, user_ids=user_ids
        )

    async def list_for_org_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
    ) -> list[RoleDTO]:
        """Return every role available in an organisation (admin tooling).

        Built-in levels come first, then the organisation's own roles. The
        four levels are not rows — they live on ``User.role`` and their
        permissions are computed — so a listing that queried only the table
        left out the roles every account in a fresh organisation actually
        holds, which is most of them.

        Carries how many people hold each one: the roles screen shows the
        number on every row, so a deletion that will be refused is visible
        before anybody clicks.
        """
        roles = await permissions_service.list_roles_for_org_async(db, organization_id)
        counts = await permissions_service.role_member_counts_async(
            db, organization_id=organization_id
        )
        custom = [
            RoleDTO.model_validate(r).model_copy(
                update={'member_count': counts.get(r.id, 0)}
            )
            for r in roles
        ]
        return await self._builtin_roles(db, organization_id) + custom

    async def _builtin_roles(
        self, db: AsyncSession, organization_id: UUID
    ) -> list[RoleDTO]:
        """The four base levels as read-only roles.

        The ids are derived from the level's name rather than stored, so they
        are the same on every request — a React key and a query cache need
        that much, and nothing may be assigned or edited by them: every
        mutating endpoint looks the id up in ``roles`` and answers 404.
        """
        counts = await permissions_service.builtin_role_member_counts_async(
            db, organization_id=organization_id
        )
        return [
            RoleDTO(
                id=uuid5(BUILTIN_ROLE_NAMESPACE, name),
                organization_id=None,
                name=name,
                permissions=sorted(builtin_role_permissions(name)),
                is_system=True,
                member_count=counts.get(name, 0),
            )
            for name in BUILTIN_ROLES
        ]

    async def create_async(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        name: str,
        permissions: list[str],
    ) -> RoleDTO:
        """Create a new org-scoped role."""
        role = await permissions_service.create_role_async(
            db,
            organization_id=organization_id,
            name=name,
            permissions=permissions,
        )
        return RoleDTO.model_validate(role)

    async def update_permissions_async(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        role_id: UUID,
        permissions: list[str],
    ) -> RoleDTO:
        """Replace the permission set on an existing role."""
        role = await permissions_service.update_role_permissions_async(
            db,
            organization_id=organization_id,
            role_id=role_id,
            permissions=permissions,
        )
        return RoleDTO.model_validate(role)

    async def org_role_map_async(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        user_ids: list[UUID],
    ) -> dict[UUID, RoleDTO]:
        """The org-scoped custom role each given user holds, keyed by user id.

        One role per person is the convention; users without one are absent
        from the map.
        """
        roles = await permissions_service.org_role_map_async(
            db, organization_id=organization_id, user_ids=user_ids
        )
        return {uid: RoleDTO.model_validate(r) for uid, r in roles.items()}

    async def assign_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        user_id: UUID,
        role_id: UUID,
        actor_user_id: UUID,
    ) -> bool:
        """Link a user to a role. Idempotent.

        Returns ``True`` when the link is newly created, ``False`` when
        the link already existed. Raises ``ValueError`` if the role
        does not exist or belongs to another organization.
        """
        return await permissions_service.assign_role_async(
            db,
            organization_id=organization_id,
            user_id=user_id,
            role_id=role_id,
            actor_user_id=actor_user_id,
        )

    async def rename_async(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        role_id: UUID,
        name: str,
    ) -> RoleDTO:
        """Give an existing org role a new name."""
        role = await permissions_service.rename_role_async(
            db, organization_id=organization_id, role_id=role_id, name=name
        )
        return RoleDTO.model_validate(role)

    async def holders_async(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        role_id: UUID,
    ) -> list[RoleHolderDTO]:
        """Everyone in the organisation who currently holds the role."""
        users = await permissions_service.role_holders_async(
            db, organization_id=organization_id, role_id=role_id
        )
        return [RoleHolderDTO.model_validate(u) for u in users]

    async def delete_async(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        role_id: UUID,
    ) -> None:
        """Delete an org role, refusing while somebody still holds it."""
        await permissions_service.delete_role_async(
            db, organization_id=organization_id, role_id=role_id
        )
