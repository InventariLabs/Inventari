import json
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import NotificationDedupKey, NotificationDTO
from app.core.db_utils import paginate_async
from app.core.logging import get_logger
from app.core.utils import isoformat_or_none
from app.models.notification import Notification
from app.models.user import User

logger = get_logger(__name__)

#: Notification copy as the public facade takes it: one string, or a language
#: table resolved per recipient (the facade documents the contract).
LocalizedText = str | Mapping[str, str]


def in_language(text: LocalizedText, lang: str | None) -> str:
    if isinstance(text, str):
        return text
    return text.get(lang or 'en', text['en'])


class NotificationService:
    @staticmethod
    def _for_user(user_id: UUID, unread_only: bool) -> Select[tuple[Notification]]:
        query = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            query = query.where(Notification.is_read.is_(False))
        return query.order_by(Notification.created_at.desc(), Notification.id)

    @staticmethod
    async def list_for_user_async(
        db: AsyncSession,
        user_id: UUID,
        unread_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Notification]:
        """Return notifications for *user_id* ordered newest first."""
        query = NotificationService._for_user(user_id, unread_only)
        result = await db.scalars(query.offset(offset).limit(limit))
        return list(result.all())

    @staticmethod
    async def page_for_user_async(
        db: AsyncSession,
        user_id: UUID,
        *,
        unread_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Notification], int]:
        """One page of *user_id*'s notifications, newest first, and their count."""
        query = NotificationService._for_user(user_id, unread_only)
        return await paginate_async(db, query, limit=limit, offset=offset)

    @staticmethod
    async def get_by_id_for_user_async(
        db: AsyncSession, notification_id: UUID, user_id: UUID
    ) -> Notification | None:
        """Return a single notification by ID scoped to *user_id*, or ``None``."""
        result = await db.scalar(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )
        return result

    @staticmethod
    async def create_notification_async(
        db: AsyncSession,
        user_id: UUID,
        title: str,
        content: str,
        type: str = 'info',
        link: str | None = None,
        meta_data: dict | None = None,
    ) -> Notification | None:
        """Persist a new in-app notification row.

        Does NOT publish to Redis — that is the caller's responsibility, after
        ``db.commit()`` so subscribers see the row before being notified.
        Use ``core_api.notifications.publish_async`` to fan out.
        """
        try:
            notification = Notification(
                user_id=user_id,
                title=title,
                content=content,
                type=type,
                link=link,
                meta_data=meta_data,
            )
            db.add(notification)
            await db.flush()
        except SQLAlchemyError as e:
            logger.error(f'Failed to create notification (async): {e}')
            return None

        return notification

    @staticmethod
    async def create_notifications_batch_async(
        db: AsyncSession,
        user_ids: list[UUID],
        title: str,
        content: str,
        type: str = 'info',
        link: str | None = None,
        meta_data: dict | None = None,
    ) -> list[Notification]:
        """Persist one notification per *user_ids* in a single flush.

        All fields carry Python-side defaults, so no refresh is needed.
        Any ``SQLAlchemyError`` aborts the batch.
        """
        if not user_ids:
            return []
        notifications = [
            Notification(
                user_id=user_id,
                title=title,
                content=content,
                type=type,
                link=link,
                meta_data=meta_data,
            )
            for user_id in user_ids
        ]
        try:
            db.add_all(notifications)
            await db.flush()
        except SQLAlchemyError as e:
            logger.error(f'Failed to create notifications (async): {e}')
            return []
        return notifications

    @staticmethod
    async def notify_superusers_async(
        db: AsyncSession,
        title: LocalizedText,
        content: LocalizedText,
        type: str = 'info',
        link: str | None = None,
        meta_data: dict | None = None,
        exclude_user_id: UUID | None = None,
    ) -> list[Notification]:
        """Persist in-app notifications for the instance's superusers.

        The readers of a request for access, which belongs to no
        organization: its list, approval and refusal sit behind
        ``get_superuser``, so the superusers are who can act on it. This
        used to ring for every ``role == 'admin'`` in every organization —
        administrators told about a request they could neither open nor
        decide, and about a person who had not asked them. An inactive
        account cannot sign in to decide anything, so it is not told
        either. ``exclude_user_id`` leaves out whoever made the act the notice
        reports: a decision is news to the other superusers, not to the one
        who has just taken it and was shown the result. ``title`` and
        ``content`` accept a language table, resolved per superuser as
        ``notify_org_admins_async`` does. Callers must commit, then call
        ``core_api.notifications.publish_async(db, notifications)``.
        """
        query = select(User.id, User.preferred_language).where(
            User.is_superuser.is_(True), User.is_active.is_(True)
        )
        if exclude_user_id is not None:
            query = query.where(User.id != exclude_user_id)
        by_language: dict[str, list[UUID]] = defaultdict(list)
        for user_id, language in (await db.execute(query)).all():
            by_language[language or 'en'].append(user_id)
        created: list[Notification] = []
        for lang, user_ids in by_language.items():
            created.extend(
                await NotificationService.create_notifications_batch_async(
                    db,
                    user_ids,
                    title=in_language(title, lang),
                    content=in_language(content, lang),
                    type=type,
                    link=link,
                    meta_data=meta_data,
                )
            )
        return created

    @staticmethod
    async def exists_unread_by_meta_async(
        db: AsyncSession,
        organization_id: UUID | None,
        key: NotificationDedupKey,
        since: datetime,
    ) -> bool:
        """Return True if an unread notification exists for the org matching
        the dedup key (``meta_data['type']`` + ``meta_data[key.ref_key]``),
        created at or after ``since``.

        Used by periodic workers to deduplicate alerts on a natural key
        (org + reference + notification type + day) before inserting.
        ``organization_id=None`` asks the same of the instance's superusers,
        who hear what belongs to no organization.
        """
        audience = (
            User.is_superuser.is_(True)
            if organization_id is None
            else User.organization_id == organization_id
        )
        stmt = (
            select(Notification.id)
            .join(User, Notification.user_id == User.id)
            .where(
                audience,
                Notification.is_read.is_(False),
                Notification.created_at >= since,
                Notification.meta_data['type'].as_string() == key.meta_type,
                Notification.meta_data[key.ref_key].as_string() == key.ref_id,
            )
            .limit(1)
        )
        return (await db.execute(stmt)).first() is not None

    @staticmethod
    async def lookup_user_org_ids_async(
        db: AsyncSession, user_ids: list[UUID]
    ) -> dict[UUID, UUID | None]:
        """Map user ids to their organization ids for the WS publish fan-out.

        Column-level read: only ``id`` + ``organization_id`` are
        fetched instead of full user rows. Users that no longer exist are
        omitted. Used by ``core_api.notifications.publish_async`` so the
        public API never imports ``app.models.user`` directly.
        """
        if not user_ids:
            return {}
        rows = (
            await db.execute(
                select(User.id, User.organization_id).where(User.id.in_(user_ids))
            )
        ).all()
        return {row.id: row.organization_id for row in rows}

    @staticmethod
    def to_dto(notification: Notification):
        """Convert a Notification ORM row to the public DTO."""
        from app.core.contracts import NotificationDTO

        return NotificationDTO.model_validate(notification)

    @staticmethod
    async def update_notification_async(
        db: AsyncSession, notification: Notification, is_read: bool
    ) -> Notification:
        """Async: update notification read status."""
        notification.is_read = is_read
        await db.flush()
        await db.refresh(notification)
        return notification

    @staticmethod
    async def mark_all_read_async(db: AsyncSession, user_id: UUID) -> None:
        """Async: mark all notifications as read for a user."""
        await db.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values({'is_read': True})
        )
        await db.flush()

    @staticmethod
    async def mark_read_by_meta_async(
        db: AsyncSession, organization_id: UUID, ref_key: str, ref_id: str
    ) -> int:
        """Mark the organization's unread notifications about one record read.

        A notification points at a record through ``meta_data[ref_key]``. When
        that record settles, the notices still asking for a decision on it have
        nothing left to ask. Scoped to the organization through the recipient.
        Returns the number of notifications changed.
        """
        org_users = select(User.id).where(User.organization_id == organization_id)
        result = await db.execute(
            update(Notification)
            .where(
                Notification.user_id.in_(org_users),
                Notification.is_read.is_(False),
                Notification.meta_data[ref_key].as_string() == ref_id,
            )
            .values({'is_read': True})
        )
        await db.flush()
        return int(getattr(result, 'rowcount', 0) or 0)

    @staticmethod
    async def delete_notification_async(
        db: AsyncSession, notification: Notification
    ) -> None:
        """Async: delete a notification."""
        await db.delete(notification)
        await db.flush()

    @staticmethod
    async def publish_async(
        db: AsyncSession,
        notifications: NotificationDTO | list[NotificationDTO] | None,
    ) -> None:
        """Publish already-committed notifications to the WS hub via Redis.

        Channels are ``notifications:user:{user_id}`` so each delivery is
        scoped to a single recipient — no cross-user leak. Failures are logged
        but never raised; the row is already persisted and the FE will refetch
        on its next polling cycle.
        """
        if not notifications:
            return
        items: list[NotificationDTO] = (
            list(notifications) if isinstance(notifications, list) else [notifications]
        )
        try:
            from app.core.events import event_bus

            redis_client = event_bus.redis
            if redis_client is None:
                return

            user_ids = [UUID(str(n.user_id)) for n in items]
            org_ids_by_user = await NotificationService.lookup_user_org_ids_async(
                db, user_ids
            )

            for n in items:
                org_id = org_ids_by_user.get(UUID(str(n.user_id)))
                if org_id is None:
                    continue
                payload = {
                    'id': str(n.id),
                    'user_id': str(n.user_id),
                    'title': n.title,
                    'content': n.content,
                    'type': n.type,
                    'link': n.link,
                    'is_read': n.is_read,
                    'created_at': isoformat_or_none(n.created_at),
                }
                await redis_client.publish(
                    f'notifications:user:{n.user_id}',
                    json.dumps(payload),
                )
        except Exception as exc:  # noqa: BLE001 — WS fanout is best-effort
            logger.warning(
                '[Notifications] Failed to publish %d notification(s): %s',
                len(items),
                exc,
            )

    @staticmethod
    async def notify_org_admins_async(
        db: AsyncSession,
        organization_id: UUID,
        title: LocalizedText,
        content: LocalizedText,
        notification_type: str = 'info',
        link: str | None = None,
        meta_data: dict[str, Any] | None = None,
    ) -> list[NotificationDTO]:
        """Notify every member who administers *organization_id*.

        An administrator is whoever holds the authority, not whoever carries
        the role's name: the built-in level, and any custom role carrying
        ``admin:access`` or ``system:config:write`` — see
        ``permissions_service.administrators_async``. Every notice "for the
        administrators" goes through here, so they all ask the same question.

        ``title`` and ``content`` accept a language table; administrators are
        then grouped by their ``preferred_language`` and each group gets the
        text it can read.

        Returns the persisted notifications so callers can pass them to
        ``publish_async`` after their own ``db.commit()``.
        """
        from app.services.user_service import UserService

        admins = await UserService.get_organization_admins_async(db, organization_id)

        if not admins:
            logger.debug(
                'notify_org_admins_async: no admins found for organization %s',
                organization_id,
            )
            return []

        by_language: dict[str, list[UUID]] = defaultdict(list)
        for admin in admins:
            by_language[admin.preferred_language or 'en'].append(admin.id)

        created = []
        for lang, user_ids in by_language.items():
            created.extend(
                await NotificationService.create_notifications_batch_async(
                    db,
                    user_ids,
                    in_language(title, lang),
                    in_language(content, lang),
                    notification_type,
                    link,
                    meta_data,
                )
            )
        return [NotificationService.to_dto(n) for n in created]


notification_service = NotificationService()
