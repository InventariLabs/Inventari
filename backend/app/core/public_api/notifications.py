"""
Module-safe notification creation API.

Modules should use this API to create in-app notifications instead of importing
``NotificationService`` directly, so that the public contract remains stable
regardless of internal refactors to the notification subsystem.

Real-time fan-out
-----------------
``create_async`` and ``notify_org_admins_async`` only persist rows. To push
the new notification through Redis Pub/Sub to the WebSocket hub, call
``publish_async(db, notifications)`` AFTER the surrounding ``db.commit()`` so
subscribers see the row before they refetch.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import NotificationDedupKey, NotificationDTO
from app.core.logging import get_logger
from app.core.public_api._scope import without_org_scope
from app.services.notification_service import NotificationService, in_language

logger = get_logger(__name__)


#: Notification copy, either as one string or as a language table.
#:
#: The rows are read months later by whoever opens the tray, so the text is
#: stored translated, not translated on the way out. A plain ``str`` is written
#: as-is; a mapping is resolved against each recipient's ``preferred_language``,
#: falling back to English. That is what keeps one table from holding "Nowy
#: wniosek o akceptację" next to "Receipt IN/2026/001 created".
LocalizedText = str | Mapping[str, str]


class CoreNotificationsAPI:
    """Public Core API for creating in-app notifications from modules."""

    @without_org_scope(
        'addressed by user_id: the notification belongs to that user, whose organization is resolved from the user'
    )
    async def create_async(
        self,
        db: AsyncSession,
        user_id: UUID,
        title: LocalizedText,
        content: LocalizedText,
        notification_type: str = 'info',
        link: str | None = None,
        meta_data: dict[str, Any] | None = None,
    ) -> NotificationDTO | None:
        """Persist a new in-app notification row.

        ``title`` and ``content`` accept a language table; the recipient's
        ``preferred_language`` decides which entry is stored.

        Returns the ``NotificationDTO`` so callers can pass it to
        ``publish_async`` after their own ``db.commit()``. The ORM object
        stays inside the Core layer.
        """
        lang = await self._language_of_async(db, user_id)
        notification = await NotificationService.create_notification_async(
            db=db,
            user_id=user_id,
            title=in_language(title, lang),
            content=in_language(content, lang),
            type=notification_type,
            link=link,
            meta_data=meta_data,
        )
        if notification is None:
            return None
        return NotificationService.to_dto(notification)  # type: ignore[no-any-return]

    async def publish_async(
        self,
        db: AsyncSession,
        notifications: NotificationDTO | list[NotificationDTO] | None,
    ) -> None:
        """Publish already-committed notifications to the WS hub via Redis.

        Channels are ``notifications:user:{user_id}`` so each delivery is
        scoped to a single recipient — no cross-user leak. Failures are logged
        but never raised; the row is already persisted and the FE will refetch
        on its next polling cycle.
        """
        await NotificationService.publish_async(db, notifications)

    async def notify_org_admins_async(
        self,
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
        return await NotificationService.notify_org_admins_async(
            db,
            organization_id,
            title,
            content,
            notification_type,
            link,
            meta_data,
        )

    @staticmethod
    def localize(table: Mapping[str, str], /, **values: object) -> dict[str, str]:
        """Fill one format string per language.

        Notification copy carries values — a document number, an item name — so
        a module declares a table of format strings and calls this to turn it
        into the table ``create_async`` / ``notify_org_admins_async`` expect.
        """
        return {lang: text.format(**values) for lang, text in table.items()}

    @staticmethod
    async def _language_of_async(db: AsyncSession, user_id: UUID) -> str | None:
        """The recipient's interface language, or None when unknown."""
        from app.services.user_service import UserService

        user = await UserService.get_by_id_model_async(db, user_id)
        return user.preferred_language if user else None

    async def exists_unread_by_meta_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        key: NotificationDedupKey,
        since: datetime,
    ) -> bool:
        """Deduplication probe for periodic alert workers.

        Returns True when an unread notification already exists for the org
        matching the dedup key, created at or after ``since``. Workers
        should call this before ``notify_org_admins_async`` to avoid
        inserting duplicate alerts on a natural key (org + reference + type
        + day).
        """
        return await NotificationService.exists_unread_by_meta_async(
            db, organization_id, key, since
        )

    async def list_for_user_async(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        unread_only: bool = False,
        skip: int = 0,
        limit: int = 50,
    ) -> list[NotificationDTO]:
        """Return notifications for *user_id* ordered newest first."""
        notifications = await NotificationService.list_for_user_async(
            db, user_id, unread_only=unread_only, offset=skip, limit=limit
        )
        return [NotificationDTO.model_validate(n) for n in notifications]

    async def get_by_id_for_user_async(
        self, db: AsyncSession, notification_id: UUID, user_id: UUID
    ) -> NotificationDTO | None:
        """Return a single notification by ID, scoped to *user_id*."""
        notification = await NotificationService.get_by_id_for_user_async(
            db, notification_id, user_id
        )
        return NotificationDTO.model_validate(notification) if notification else None

    @without_org_scope(
        'addressed by user_id: the notification belongs to that user, whose organization is resolved from the user'
    )
    async def update_read_status_async(
        self, db: AsyncSession, notification_id: UUID, user_id: UUID, is_read: bool
    ) -> NotificationDTO | None:
        """Update a notification's read status. Returns the updated DTO or None."""
        notification = await NotificationService.get_by_id_for_user_async(
            db, notification_id, user_id
        )
        if notification is None:
            return None
        updated = await NotificationService.update_notification_async(
            db, notification, is_read
        )
        return NotificationDTO.model_validate(updated) if updated else None

    @without_org_scope(
        'addressed by user_id: the notification belongs to that user, whose organization is resolved from the user'
    )
    async def mark_all_read_async(self, db: AsyncSession, user_id: UUID) -> None:
        """Mark all notifications as read for *user_id*."""
        await NotificationService.mark_all_read_async(db, user_id)

    async def mark_read_by_meta_async(
        self, db: AsyncSession, organization_id: UUID, ref_key: str, ref_id: str
    ) -> int:
        """Mark the org's unread notifications about one record as read.

        Matches ``meta_data[ref_key] == ref_id``, so a module that settles a
        record clears the notices that were still asking for a decision on it.
        Returns how many notifications changed.
        """
        return await NotificationService.mark_read_by_meta_async(
            db, organization_id, ref_key, ref_id
        )

    @without_org_scope(
        'addressed by user_id: the notification belongs to that user, whose organization is resolved from the user'
    )
    async def delete_async(
        self, db: AsyncSession, notification_id: UUID, user_id: UUID
    ) -> bool:
        """Delete a notification. Returns ``True`` if deleted, ``False`` if not found."""
        notification = await NotificationService.get_by_id_for_user_async(
            db, notification_id, user_id
        )
        if notification is None:
            return False
        await NotificationService.delete_notification_async(db, notification)
        return True
