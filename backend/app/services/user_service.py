from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import escape_ilike
from app.core.logging import get_logger
from app.models.user import User
from app.services.permissions_service import administrators_async

logger = get_logger(__name__)


class UserService:
    @staticmethod
    async def get_users_by_ids_async(
        db: AsyncSession, user_ids: list[UUID]
    ) -> list[User]:
        """Batch-load users by id list. Returns empty list for empty input.

        Use for enrichment paths that reference many users (e.g. approval
        requests with N decisions each having an approver). Avoids the
        N+1 query pattern of calling ``get_by_id_model_async`` per id.
        """
        if not user_ids:
            return []
        result = await db.scalars(select(User).where(User.id.in_(user_ids)))
        return list(result.all())

    @staticmethod
    async def get_organization_members_async(
        db: AsyncSession,
        organization_id: UUID,
        only_active: bool = True,
        offset: int = 0,
        limit: int | None = None,
        search: str | None = None,
    ) -> list[User]:
        query = select(User).where(User.organization_id == organization_id)
        if only_active:
            query = query.where(User.is_active.is_(True))
        if search:
            pattern = f'%{escape_ilike(search)}%'
            query = query.where(
                or_(
                    User.email.ilike(pattern),
                    User.full_name.ilike(pattern),
                )
            )
        if limit is not None:
            query = query.offset(offset).limit(limit)
        result = await db.scalars(query)
        return list(result.all())

    @staticmethod
    async def get_organization_admins_async(
        db: AsyncSession, organization_id: UUID
    ) -> list[User]:
        """The active members who administer *organization_id*.

        Resolved by permission, not by the role's name — see
        ``permissions_service.administrators_async``.
        """
        ids = await administrators_async(db, organization_id=organization_id)
        if not ids:
            return []
        result = await db.scalars(
            select(User).where(User.id.in_(ids)).order_by(User.created_at, User.id)
        )
        return list(result.all())

    @staticmethod
    async def update_user_status_async(
        db: AsyncSession,
        user: User,
        is_active: bool | None = None,
        is_blocked: bool | None = None,
        blocked_at=None,
        blocking_reason: str | None = None,
    ) -> User:
        if is_active is not None:
            user.is_active = is_active
        if is_blocked is not None:
            user.is_blocked = is_blocked
        if blocked_at is not None or is_blocked is False:
            user.blocked_at = blocked_at
        if blocking_reason is not None or is_blocked is False:
            user.blocking_reason = blocking_reason

        await db.flush()
        await db.refresh(user)
        return user

    @staticmethod
    async def get_user_by_email_async(db: AsyncSession, email: str) -> User | None:
        return await db.scalar(select(User).where(User.email == email))

    @staticmethod
    async def get_first_by_created_at_async(
        db: AsyncSession, organization_id: UUID | None = None
    ) -> User | None:
        """Async variant for async callers."""
        query = select(User)
        if organization_id is not None:
            query = query.where(User.organization_id == organization_id)
        result = await db.scalars(query.order_by(User.created_at.asc()))
        return result.first()

    @staticmethod
    async def promote_superuser_async(db: AsyncSession, user_id: UUID) -> User | None:
        user = await db.scalar(select(User).where(User.id == user_id))
        if not user:
            return None
        user.is_superuser = True
        await db.flush()
        await db.refresh(user)
        return user

    @staticmethod
    async def get_by_id_in_org_async(
        db: AsyncSession, user_id: UUID, organization_id: UUID
    ) -> User | None:
        """Async: get a user by id within a specific organization."""
        result = await db.scalar(
            select(User).where(
                User.id == user_id,
                User.organization_id == organization_id,
            )
        )
        return result

    @staticmethod
    async def get_by_id_model_async(db: AsyncSession, user_id: UUID) -> User | None:
        """Async: get the raw User model by id.

        Intentionally NOT scoped by organization_id — used for JWT
        subject→User resolution where the org is not yet known (it is
        resolved *from* the user record).  All org-scoped reads must use
        ``get_by_id_async`` or ``get_users_async`` instead.
        """
        result = await db.scalar(select(User).where(User.id == user_id))
        return result

    @staticmethod
    async def count_async(db: AsyncSession, organization_id: UUID | None = None) -> int:
        query = select(func.count(User.id))
        if organization_id is not None:
            query = query.where(User.organization_id == organization_id)
        result = await db.scalar(query)
        return result or 0

    @staticmethod
    async def list_all_with_organization_async(db: AsyncSession) -> list[User]:
        """List all users with the organization relationship eagerly loaded.

        Returns SQLAlchemy ``User`` ORM objects so callers can use
        ``UserSchema`` (``from_attributes=True``). Ordered by email.
        """
        from sqlalchemy.orm import joinedload

        result = await db.execute(
            select(User).options(joinedload(User.organization)).order_by(User.email)
        )
        return list(result.unique().scalars().all())
