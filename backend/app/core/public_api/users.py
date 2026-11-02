"""
CoreUsersAPI — module-safe read/write access to user data.

DTO-only surface: ORM-level user access stays inside Core —
``UserService`` is used directly by ``app/api/organizations.py`` and other
Core-internal callers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserDTO
from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.models.user import User

logger = get_logger(__name__)

# Re-export UserProfileDTO from contracts for backward compatibility.
from app.core.contracts import UserProfileDTO  # noqa: E402, F401


def _to_dto(user: User) -> UserProfileDTO:
    return UserProfileDTO(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        organization_id=user.organization_id,
        preferred_language=user.preferred_language,
    )


def _to_full_dto(user: User) -> UserDTO:
    return UserDTO.model_validate(user)


def _in_org(user: User, organization_id: UUID | None) -> bool:
    """True when *user* is visible from *organization_id*.

    ``None`` means the caller deliberately asked for the cross-org view
    (superuser tooling, bootstrap before any organization exists).
    """
    return organization_id is None or user.organization_id == organization_id


class CoreUsersAPI:
    """Public Core API for module-safe user access."""

    async def get_async(
        self, db: AsyncSession, organization_id: UUID | None, user_id: UUID
    ) -> UserProfileDTO | None:
        """Load a user profile, scoped to *organization_id*.

        ``organization_id=None`` is the deliberate cross-org path (superuser
        tooling, bootstrap). It has no default, so a module cannot slip into
        it by omission — which is exactly how this method used to let a
        module read a user from another organization by id alone.
        """
        from app.services.user_service import UserService

        user = await UserService.get_by_id_model_async(db, user_id)
        if not user or not _in_org(user, organization_id):
            return None
        return _to_dto(user)

    async def get_by_ids_async(
        self, db: AsyncSession, organization_id: UUID | None, user_ids: list[UUID]
    ) -> list[UserProfileDTO]:
        """Batch-load user profiles by id list (single IN-query).

        Use for enrichment paths that reference many users (e.g. approval
        requests with N decisions each having an approver). Avoids the N+1
        query pattern of calling ``get_async`` per id. Returns an empty
        list for empty input.
        """
        from app.services.user_service import UserService

        users = await UserService.get_users_by_ids_async(db, user_ids)
        return [_to_dto(u) for u in users if _in_org(u, organization_id)]

    async def get_full_async(
        self, db: AsyncSession, organization_id: UUID | None, user_id: UUID
    ) -> UserDTO | None:
        from app.services.user_service import UserService

        user = await UserService.get_by_id_model_async(db, user_id)
        if not user or not _in_org(user, organization_id):
            return None
        return _to_full_dto(user)

    async def get_first_system_user_async(self, db: AsyncSession) -> UserDTO | None:
        """Return the oldest user across ALL organizations (org-less global read).

        Reserved for startup/bootstrap repair paths that run before any
        organization context exists (``bootstrap_service``). Never use in
        tenant-scoped request handlers — use :meth:`get_first_by_created_at_async`.
        """
        from app.services.user_service import UserService

        user = await UserService.get_first_by_created_at_async(db, None)
        if not user:
            return None
        return _to_full_dto(user)

    async def promote_superuser_async(
        self, db: AsyncSession, user_id: UUID
    ) -> UserDTO | None:
        """Promote a user to superuser (startup repair only)."""
        from app.services.user_service import UserService

        user = await UserService.promote_superuser_async(db, user_id)
        if not user:
            return None
        return _to_full_dto(user)

    async def list_org_members_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        offset: int = 0,
        limit: int | None = None,
        search: str | None = None,
    ) -> list[UserDTO]:
        """

        ``offset``/``limit``/``search`` are passed through to
        ``UserService``. When ``limit`` is ``None`` the full list is
        returned (kept for callers like ``cloud_service.py`` that still
        need unscoped reads).
        """
        from app.services.user_service import UserService

        users = await UserService.get_organization_members_async(
            db,
            organization_id,
            offset=offset,
            limit=limit,
            search=search,
        )
        return [UserDTO.model_validate(u) for u in users]

    async def get_by_email_async(
        self, db: AsyncSession, organization_id: UUID | None, email: str
    ) -> UserDTO | None:
        """Get a user DTO by email, scoped to *organization_id*.

        An email is far easier to guess than a UUID, so an unscoped lookup
        here was user enumeration across organizations, not just a leak of
        one record. ``None`` remains available for the bootstrap path, where
        no organization exists yet.
        """
        from app.services.user_service import UserService

        user = await UserService.get_user_by_email_async(db, email)
        if not user or not _in_org(user, organization_id):
            return None
        return _to_full_dto(user)

    async def get_by_id_in_org_async(
        self, db: AsyncSession, user_id: UUID, organization_id: UUID
    ) -> UserDTO | None:
        """Async: get a User DTO by id within a specific organization, or None."""
        from app.services.user_service import UserService

        user = await UserService.get_by_id_in_org_async(db, user_id, organization_id)
        return UserDTO.model_validate(user) if user else None

    async def count_async(self, db: AsyncSession, organization_id: UUID) -> int:
        """Async: count users in an organization (used by list_all_organizations)."""
        from app.services.user_service import UserService

        return await UserService.count_async(db, organization_id)

    async def list_all_async(self, db: AsyncSession) -> list[UserDTO]:
        """List all users (superuser view) with organization eagerly loaded."""
        from app.services.user_service import UserService

        users = await UserService.list_all_with_organization_async(db)
        return [UserDTO.model_validate(u) for u in users]

    async def _journal_member_status_async(
        self,
        db: AsyncSession,
        user: User,
        *,
        actor_user_id: UUID | None,
        before: dict[str, object],
        after: dict[str, object],
        reason: str | None = None,
    ) -> None:
        """Record a status change on a member, in the write's transaction.

        The entry rides the caller's transaction with the change
        ``UserService`` flushes, so the two stand or fall together. An account
        without an organization
        has no tenant to write the entry into.
        """
        from app.core.contracts import AuditAction, AuditTargetType
        from app.services.audit_service import log_action_async

        assert user.organization_id is not None  # guarded by the callers
        await log_action_async(
            db,
            organization_id=user.organization_id,
            user_id=actor_user_id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.ORG_MEMBER,
            target_id=user.id,
            snapshot={'name': user.email, 'before': before, 'after': after},
            reason=reason,
        )

    async def activate_or_deactivate_async(
        self,
        db: AsyncSession,
        organization_id: UUID | None,
        user_id: UUID,
        *,
        actor_user_id: UUID | None = None,
    ) -> UserDTO | None:
        """Toggle a user's ``is_active`` flag. Returns updated user, or None.

        Without the org parameter this mutated accounts in any
        organization on nothing but a user id.
        """
        from app.services.user_service import UserService

        user = await UserService.get_by_id_model_async(db, user_id)
        if not user or not _in_org(user, organization_id):
            return None
        if user.organization_id is not None:
            await self._journal_member_status_async(
                db,
                user,
                actor_user_id=actor_user_id,
                before={'is_active': user.is_active},
                after={'is_active': not user.is_active},
            )
        updated = await UserService.update_user_status_async(
            db, user, is_active=not user.is_active
        )
        return UserDTO.model_validate(updated) if updated else None

    async def block_async(
        self,
        db: AsyncSession,
        organization_id: UUID | None,
        user_id: UUID,
        reason: str | None,
        *,
        actor_user_id: UUID | None = None,
    ) -> UserDTO | None:
        """Block a user with optional reason. Returns updated user, or None.

        Blocking an already blocked account changes nothing, so neither the
        write nor the journal gains a second entry for it.
        """
        from app.services.user_service import UserService

        user = await UserService.get_by_id_model_async(db, user_id)
        if not user or not _in_org(user, organization_id):
            return None
        if user.organization_id is not None and not user.is_blocked:
            await self._journal_member_status_async(
                db,
                user,
                actor_user_id=actor_user_id,
                before={'is_blocked': False},
                after={'is_blocked': True},
                reason=reason,
            )
        updated = await UserService.update_user_status_async(
            db,
            user,
            is_blocked=True,
            blocked_at=datetime.now(UTC),
            blocking_reason=reason,
        )
        return UserDTO.model_validate(updated) if updated else None

    async def unblock_async(
        self,
        db: AsyncSession,
        organization_id: UUID | None,
        user_id: UUID,
        *,
        actor_user_id: UUID | None = None,
    ) -> UserDTO | None:
        """Unblock a user. Returns updated user, or None.

        Unblocking an account that is not blocked changes nothing, so no
        entry is written for it.
        """
        from app.services.user_service import UserService

        user = await UserService.get_by_id_model_async(db, user_id)
        if not user or not _in_org(user, organization_id):
            return None
        if user.organization_id is not None and user.is_blocked:
            await self._journal_member_status_async(
                db,
                user,
                actor_user_id=actor_user_id,
                before={'is_blocked': True},
                after={'is_blocked': False},
            )
        updated = await UserService.update_user_status_async(
            db, user, is_blocked=False, blocked_at=None, blocking_reason=None
        )
        return UserDTO.model_validate(updated) if updated else None
