"""
Integration tests for NotificationService.

Tests cover:
- Creating notifications for individual users
- Batch notifications (notify_superusers)
- Error handling and rollback behavior
- Various notification types and metadata
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import NotificationDedupKey
from app.models.notification import Notification
from app.models.user import User
from app.services.notification_service import NotificationService


@pytest.fixture
async def async_db(real_async_db_session: AsyncSession):
    """Async session with clean state for test isolation.

    Truncates ``notifications`` and ``users`` tables so each async test
    starts from a blank slate, regardless of what earlier tests committed.
    """
    await real_async_db_session.execute(
        text('TRUNCATE notifications, users RESTART IDENTITY CASCADE')
    )
    await real_async_db_session.commit()
    yield real_async_db_session


@pytest.fixture
async def async_user(async_db: AsyncSession):
    """Create a member user inside the savepoint."""
    from app.services.token_service import get_password_hash

    user = User(
        email=f'async-notif-{uuid.uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Async Notif User',
        role='member',
        is_active=True,
    )
    async_db.add(user)
    await async_db.flush()
    await async_db.refresh(user)
    return user


@pytest.fixture
async def async_admin(async_db: AsyncSession):
    """Create an admin user inside the savepoint."""
    from app.services.token_service import get_password_hash

    admin = User(
        email=f'async-admin-{uuid.uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Async Admin',
        role='admin',
        is_active=True,
    )
    async_db.add(admin)
    await async_db.flush()
    await async_db.refresh(admin)
    return admin


@pytest.mark.integration
@pytest.mark.asyncio
class TestNotificationService:
    """NotificationService integration tests."""

    async def test_create_notification_basic(self, async_db, async_user):
        """Test creating a basic notification for a user."""
        title = 'Test Title'
        content = 'Test Content'
        type_val = 'info'

        result = await NotificationService.create_notification_async(
            db=async_db,
            user_id=async_user.id,
            title=title,
            content=content,
            type=type_val,
        )

        assert result is not None
        assert result.user_id == async_user.id
        assert result.title == title
        assert result.content == content
        assert result.type == type_val
        assert result.link is None
        assert result.meta_data is None

        # Verify persisted in DB
        db_notification = (
            await async_db.scalars(
                select(Notification).where(Notification.id == result.id)
            )
        ).first()
        assert db_notification is not None
        assert db_notification.title == title

    async def test_create_notification_with_link(self, async_db, async_user):
        """Test creating notification with link."""
        link = '/items/123/details'

        result = await NotificationService.create_notification_async(
            db=async_db,
            user_id=async_user.id,
            title='Item Update',
            content='An item was moved',
            type='update',
            link=link,
        )

        assert result.link == link

    async def test_create_notification_with_metadata(self, async_db, async_user):
        """Test creating notification with metadata."""
        meta = {'item_id': 'STM-001', 'old_location': 'A1', 'new_location': 'B2'}

        result = await NotificationService.create_notification_async(
            db=async_db,
            user_id=async_user.id,
            title='Item Moved',
            content='Item was moved to new location',
            meta_data=meta,
        )

        assert result.meta_data == meta
        assert result.meta_data['item_id'] == 'STM-001'

    async def test_create_notification_warning_type(self, async_db, async_user):
        """Test creating warning type notification."""
        result = await NotificationService.create_notification_async(
            db=async_db,
            user_id=async_user.id,
            title='Low Stock Warning',
            content='Item stock is below minimum',
            type='warning',
        )

        assert result.type == 'warning'

    async def test_create_notification_error_type(self, async_db, async_user):
        """Test creating error type notification."""
        result = await NotificationService.create_notification_async(
            db=async_db,
            user_id=async_user.id,
            title='Operation Failed',
            content='Failed to process request',
            type='error',
        )

        assert result.type == 'error'

    async def test_create_notification_success_type(self, async_db, async_user):
        """Test creating success type notification."""
        result = await NotificationService.create_notification_async(
            db=async_db,
            user_id=async_user.id,
            title='Item Created',
            content='New item was successfully created',
            type='success',
        )

        assert result.type == 'success'

    async def test_create_notification_multiple_for_same_user(
        self, async_db, async_user
    ):
        """Test creating multiple notifications for same user."""
        # Create first notification
        result1 = await NotificationService.create_notification_async(
            db=async_db,
            user_id=async_user.id,
            title='First',
            content='First notification',
        )

        # Create second notification
        result2 = await NotificationService.create_notification_async(
            db=async_db,
            user_id=async_user.id,
            title='Second',
            content='Second notification',
        )

        assert result1.id != result2.id
        assert result1.user_id == result2.user_id == async_user.id

        # Verify both exist in DB
        notifications = list(
            (
                await async_db.scalars(
                    select(Notification).where(Notification.user_id == async_user.id)
                )
            ).all()
        )
        assert len(notifications) >= 2

    async def test_create_notification_returns_none_on_error(
        self, async_db, async_user, monkeypatch
    ):
        """Test that create_notification_async returns None on DB error."""

        original_flush = AsyncSession.flush

        async def mock_flush(self, *args, **kwargs):
            raise SQLAlchemyError('Database error')

        monkeypatch.setattr(AsyncSession, 'flush', mock_flush)

        result = await NotificationService.create_notification_async(
            db=async_db,
            user_id=async_user.id,
            title='Test',
            content='Test',
        )

        monkeypatch.setattr(AsyncSession, 'flush', original_flush)
        assert result is None

    async def test_notify_superusers_single_superuser(self, async_db, async_user):
        """The one superuser there is gets the notification."""
        async_user.is_superuser = True
        await async_db.flush()

        title = 'System Alert'
        results = await NotificationService.notify_superusers_async(
            db=async_db,
            title=title,
            content='This is for whoever can decide it',
            type='alert',
        )

        assert any(n.user_id == async_user.id for n in results)
        stored = (
            await async_db.scalars(
                select(Notification).where(
                    Notification.user_id == async_user.id,
                    Notification.title == title,
                )
            )
        ).all()
        assert len(stored) == 1

    async def test_notify_superusers_multiple_superusers(self, async_db, async_user):
        """Every superuser is told, whichever organization they sit in."""
        async_user.is_superuser = True
        others = [
            User(
                email=f'super{i}-{uuid.uuid4().hex[:6]}@test.com',
                hashed_password='hash',
                full_name=f'Super {i}',
                role='admin',
                is_superuser=True,
                is_active=True,
            )
            for i in (2, 3)
        ]
        async_db.add_all(others)
        await async_db.flush()

        results = await NotificationService.notify_superusers_async(
            db=async_db,
            title='Critical System Alert',
            content='Every superuser needs to see this',
            type='alert',
        )

        told = {n.user_id for n in results}
        for superuser in [async_user, *others]:
            assert superuser.id in told

    async def test_notify_superusers_skips_administrators(self, async_db, async_user):
        """An administrator who is not a superuser cannot open the request,
        so is not told about it."""
        superuser = User(
            email=f'super-{uuid.uuid4().hex[:6]}@test.com',
            hashed_password='hash',
            full_name='Superuser',
            role='admin',
            is_superuser=True,
            is_active=True,
        )
        async_db.add(superuser)
        async_user.role = 'admin'
        async_user.is_superuser = False
        await async_db.flush()

        results = await NotificationService.notify_superusers_async(
            db=async_db,
            title='Superusers only',
            content='An administrator should not get this',
        )

        told = {n.user_id for n in results}
        assert superuser.id in told
        assert async_user.id not in told

    async def test_notify_superusers_skips_an_inactive_superuser(
        self, async_db, async_user
    ):
        """An account that cannot sign in cannot decide anything either."""
        async_user.is_superuser = True
        async_user.is_active = False
        await async_db.flush()

        results = await NotificationService.notify_superusers_async(
            db=async_db, title='Alert', content='Nobody signed out should get this'
        )

        assert async_user.id not in {n.user_id for n in results}

    async def test_notify_superusers_with_link(self, async_db, async_user):
        async_user.is_superuser = True
        await async_db.flush()

        link = '/admin/dashboard/alerts'
        results = await NotificationService.notify_superusers_async(
            db=async_db,
            title='Alert',
            content='Check alerts',
            link=link,
        )

        assert results
        assert all(n.link == link for n in results)

    async def test_notify_superusers_with_metadata(self, async_db, async_user):
        async_user.is_superuser = True
        await async_db.flush()

        meta = {'alert_id': 'ALT-001', 'severity': 'high'}
        results = await NotificationService.notify_superusers_async(
            db=async_db,
            title='Alert',
            content='High priority alert',
            meta_data=meta,
        )

        assert results
        assert all(n.meta_data == meta for n in results)

    async def test_notify_superusers_returns_empty_list_on_error(
        self, async_db, async_user, monkeypatch
    ):
        async_user.is_superuser = True
        await async_db.flush()

        async def failing_flush(self, *args, **kwargs):
            raise SQLAlchemyError('Database error')

        monkeypatch.setattr(AsyncSession, 'flush', failing_flush)
        results = await NotificationService.notify_superusers_async(
            db=async_db,
            title='Alert',
            content='Will fail',
        )
        monkeypatch.undo()

        assert results == []

    async def test_notify_superusers_returns_empty_list_when_none(self, async_db):
        results = await NotificationService.notify_superusers_async(
            db=async_db,
            title='Alert',
            content='No one to notify',
        )

        assert results == []

    async def test_notification_service_singleton(self):
        """Test that notification_service is properly initialized."""
        from app.services.notification_service import notification_service

        assert notification_service is not None
        assert isinstance(notification_service, NotificationService)


@pytest.mark.integration
@pytest.mark.asyncio
class TestListForUserAsync:
    """Tests for NotificationService.list_for_user_async."""

    async def test_returns_all_notifications_for_user(
        self,
        async_db: AsyncSession,
        async_user: User,
    ):
        for i in range(3):
            async_db.add(
                Notification(
                    user_id=async_user.id,
                    title=f'N{i}',
                    content='C',
                    is_read=False,
                )
            )
        await async_db.flush()

        results = await NotificationService.list_for_user_async(
            db=async_db,
            user_id=async_user.id,
        )

        assert len(results) == 3

    async def test_unread_only_filter(
        self,
        async_db: AsyncSession,
        async_user: User,
    ):
        async_db.add(
            Notification(
                user_id=async_user.id,
                title='Unread',
                content='C',
                is_read=False,
            )
        )
        async_db.add(
            Notification(
                user_id=async_user.id,
                title='Read',
                content='C',
                is_read=True,
            )
        )
        await async_db.flush()

        results = await NotificationService.list_for_user_async(
            db=async_db,
            user_id=async_user.id,
            unread_only=True,
        )

        assert len(results) == 1
        assert results[0].title == 'Unread'

    async def test_skip_and_limit(
        self,
        async_db: AsyncSession,
        async_user: User,
    ):
        for i in range(5):
            async_db.add(
                Notification(
                    user_id=async_user.id,
                    title=f'N{i}',
                    content='C',
                )
            )
        await async_db.flush()

        page = await NotificationService.list_for_user_async(
            db=async_db,
            user_id=async_user.id,
            offset=2,
            limit=2,
        )

        assert len(page) == 2

    async def test_empty_when_no_notifications(
        self,
        async_db: AsyncSession,
        async_user: User,
    ):
        results = await NotificationService.list_for_user_async(
            db=async_db,
            user_id=async_user.id,
        )
        assert results == []

    async def test_ordered_newest_first(
        self,
        async_db: AsyncSession,
        async_user: User,
    ):
        n1 = Notification(user_id=async_user.id, title='First', content='C')
        async_db.add(n1)
        await async_db.flush()
        await async_db.refresh(n1)

        n2 = Notification(user_id=async_user.id, title='Second', content='C')
        async_db.add(n2)
        await async_db.flush()
        await async_db.refresh(n2)

        results = await NotificationService.list_for_user_async(
            db=async_db,
            user_id=async_user.id,
        )

        assert results[0].title == 'Second'
        assert results[1].title == 'First'


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetByIdForUserAsync:
    """Tests for NotificationService.get_by_id_for_user_async."""

    async def test_returns_notification_when_found(
        self,
        async_db: AsyncSession,
        async_user: User,
    ):
        n = Notification(
            user_id=async_user.id,
            title='Find Me',
            content='C',
        )
        async_db.add(n)
        await async_db.flush()
        await async_db.refresh(n)

        result = await NotificationService.get_by_id_for_user_async(
            db=async_db,
            notification_id=n.id,
            user_id=async_user.id,
        )

        assert result is not None
        assert result.id == n.id

    async def test_returns_none_when_not_found(
        self,
        async_db: AsyncSession,
        async_user: User,
    ):
        from uuid import uuid4

        result = await NotificationService.get_by_id_for_user_async(
            db=async_db,
            notification_id=uuid4(),
            user_id=async_user.id,
        )

        assert result is None

    async def test_returns_none_for_wrong_user(
        self,
        async_db: AsyncSession,
        async_user: User,
        async_admin: User,
    ):
        n = Notification(
            user_id=async_user.id,
            title='Not Yours',
            content='C',
        )
        async_db.add(n)
        await async_db.flush()
        await async_db.refresh(n)

        result = await NotificationService.get_by_id_for_user_async(
            db=async_db,
            notification_id=n.id,
            user_id=async_admin.id,
        )

        assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestNotifySuperusersAsync:
    """Tests for NotificationService.notify_superusers_async."""

    async def test_creates_notification_for_each_superuser(
        self,
        async_db: AsyncSession,
        async_admin: User,
    ):
        async_admin.is_superuser = True
        admin2 = User(
            email=f'async-admin2-{uuid.uuid4().hex[:8]}@test.com',
            hashed_password='hash',
            full_name='Admin Two',
            role='admin',
            is_superuser=True,
            is_active=True,
        )
        async_db.add(admin2)
        await async_db.flush()
        await async_db.refresh(admin2)

        results = await NotificationService.notify_superusers_async(
            db=async_db,
            title='Alert',
            content='For superusers',
        )

        assert len(results) >= 2
        admin_ids = {n.user_id for n in results}
        assert async_admin.id in admin_ids
        assert admin2.id in admin_ids

    async def test_with_link_and_metadata(
        self,
        async_db: AsyncSession,
        async_admin: User,
    ):
        async_admin.is_superuser = True
        await async_db.flush()
        meta = {'severity': 'high'}

        results = await NotificationService.notify_superusers_async(
            db=async_db,
            title='Alert',
            content='C',
            link='/alerts/1',
            meta_data=meta,
        )

        assert len(results) >= 1
        assert all(n.link == '/alerts/1' for n in results)
        assert all(n.meta_data == meta for n in results)

    async def test_returns_empty_when_no_superusers(
        self,
        async_db: AsyncSession,
        async_user: User,
    ):
        results = await NotificationService.notify_superusers_async(
            db=async_db,
            title='Alert',
            content='C',
        )
        assert results == []

    async def test_notification_type_defaults_to_info(
        self,
        async_db: AsyncSession,
        async_admin: User,
    ):
        async_admin.is_superuser = True
        await async_db.flush()
        results = await NotificationService.notify_superusers_async(
            db=async_db,
            title='T',
            content='C',
        )

        assert len(results) >= 1
        assert all(n.type == 'info' for n in results)


@pytest.mark.integration
@pytest.mark.asyncio
class TestUpdateNotificationAsync:
    """Tests for NotificationService.update_notification_async."""

    async def test_marks_as_read(
        self,
        async_db: AsyncSession,
        async_user: User,
    ):
        n = Notification(
            user_id=async_user.id,
            title='T',
            content='C',
            is_read=False,
        )
        async_db.add(n)
        await async_db.flush()
        await async_db.refresh(n)

        result = await NotificationService.update_notification_async(
            db=async_db,
            notification=n,
            is_read=True,
        )

        assert result.is_read is True

    async def test_marks_as_unread(
        self,
        async_db: AsyncSession,
        async_user: User,
    ):
        n = Notification(
            user_id=async_user.id,
            title='T',
            content='C',
            is_read=True,
        )
        async_db.add(n)
        await async_db.flush()
        await async_db.refresh(n)

        result = await NotificationService.update_notification_async(
            db=async_db,
            notification=n,
            is_read=False,
        )

        assert result.is_read is False


@pytest.mark.integration
@pytest.mark.asyncio
class TestMarkAllReadAsync:
    """Tests for NotificationService.mark_all_read_async."""

    async def test_marks_all_unread_as_read(
        self,
        async_db: AsyncSession,
        async_user: User,
    ):
        for i in range(3):
            async_db.add(
                Notification(
                    user_id=async_user.id,
                    title=f'N{i}',
                    content='C',
                    is_read=False,
                )
            )
        await async_db.flush()

        await NotificationService.mark_all_read_async(
            db=async_db,
            user_id=async_user.id,
        )

        unread = (
            await async_db.scalars(
                select(Notification).where(
                    Notification.user_id == async_user.id,
                    Notification.is_read.is_(False),
                )
            )
        ).all()
        assert len(unread) == 0

    async def test_noop_when_no_notifications(
        self,
        async_db: AsyncSession,
        async_user: User,
    ):
        await NotificationService.mark_all_read_async(
            db=async_db,
            user_id=async_user.id,
        )

    async def test_only_affects_target_user(
        self,
        async_db: AsyncSession,
        async_user: User,
        async_admin: User,
    ):
        async_db.add(
            Notification(
                user_id=async_user.id,
                title='A',
                content='C',
                is_read=False,
            )
        )
        async_db.add(
            Notification(
                user_id=async_admin.id,
                title='B',
                content='C',
                is_read=False,
            )
        )
        await async_db.flush()

        await NotificationService.mark_all_read_async(
            db=async_db,
            user_id=async_user.id,
        )

        admin_unread = (
            await async_db.scalars(
                select(Notification).where(
                    Notification.user_id == async_admin.id,
                    Notification.is_read.is_(False),
                )
            )
        ).all()
        assert len(admin_unread) == 1


@pytest.mark.integration
@pytest.mark.asyncio
class TestDeleteNotificationAsync:
    """Tests for NotificationService.delete_notification_async."""

    async def test_deletes_notification(
        self,
        async_db: AsyncSession,
        async_user: User,
    ):
        n = Notification(user_id=async_user.id, title='Delete Me', content='C')
        async_db.add(n)
        await async_db.flush()
        await async_db.refresh(n)
        notif_id = n.id

        await NotificationService.delete_notification_async(db=async_db, notification=n)

        result = (
            await async_db.scalars(
                select(Notification).where(Notification.id == notif_id)
            )
        ).first()
        assert result is None

    async def test_does_not_affect_other_notifications(
        self,
        async_db: AsyncSession,
        async_user: User,
    ):
        n1 = Notification(user_id=async_user.id, title='Keep', content='C')
        n2 = Notification(user_id=async_user.id, title='Remove', content='C')
        async_db.add_all([n1, n2])
        await async_db.flush()
        await async_db.refresh(n1)
        await async_db.refresh(n2)

        await NotificationService.delete_notification_async(
            db=async_db, notification=n2
        )

        remaining = (
            await async_db.scalars(
                select(Notification).where(
                    Notification.user_id == async_user.id,
                )
            )
        ).all()
        assert len(remaining) == 1
        assert remaining[0].id == n1.id


@pytest.mark.integration
@pytest.mark.asyncio
class TestExistsUnreadByMetaAsync:
    """Dedup probe used by periodic alert workers."""

    async def _make_notification(
        self,
        async_db: AsyncSession,
        user_id: uuid.UUID,
        *,
        is_read: bool = False,
        meta: dict | None = None,
        created_at: 'datetime | None' = None,
    ) -> Notification:
        n = Notification(
            user_id=user_id,
            title='T',
            content='C',
            is_read=is_read,
            meta_data=meta,
        )
        async_db.add(n)
        await async_db.flush()
        if created_at is not None:
            await async_db.execute(
                text('UPDATE notifications SET created_at = :ts WHERE id = :id'),
                {'ts': created_at, 'id': n.id},
            )
        return n

    async def test_true_for_matching_unread(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user: User,
    ):
        await self._make_notification(
            real_async_db_session,
            async_test_user.id,
            meta={'type': 'equipment_warranty', 'item_id': 'abc-123'},
        )
        exists = await NotificationService.exists_unread_by_meta_async(
            real_async_db_session,
            async_test_household.id,
            NotificationDedupKey(
                meta_type='equipment_warranty', ref_key='item_id', ref_id='abc-123'
            ),
            since=datetime.now(UTC) - timedelta(hours=1),
        )
        assert exists is True

    async def test_false_when_already_read(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user: User,
    ):
        await self._make_notification(
            real_async_db_session,
            async_test_user.id,
            is_read=True,
            meta={'type': 'equipment_warranty', 'item_id': 'abc-123'},
        )
        exists = await NotificationService.exists_unread_by_meta_async(
            real_async_db_session,
            async_test_household.id,
            NotificationDedupKey(
                meta_type='equipment_warranty', ref_key='item_id', ref_id='abc-123'
            ),
            since=datetime.now(UTC) - timedelta(hours=1),
        )
        assert exists is False

    async def test_false_for_different_reference(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user: User,
    ):
        await self._make_notification(
            real_async_db_session,
            async_test_user.id,
            meta={'type': 'equipment_warranty', 'item_id': 'other-item'},
        )
        exists = await NotificationService.exists_unread_by_meta_async(
            real_async_db_session,
            async_test_household.id,
            NotificationDedupKey(
                meta_type='equipment_warranty', ref_key='item_id', ref_id='abc-123'
            ),
            since=datetime.now(UTC) - timedelta(hours=1),
        )
        assert exists is False

    async def test_false_when_created_before_since(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user: User,
    ):
        await self._make_notification(
            real_async_db_session,
            async_test_user.id,
            meta={'type': 'equipment_overdue', 'assignment_id': 'a-1'},
            created_at=datetime.now(UTC) - timedelta(days=2),
        )
        exists = await NotificationService.exists_unread_by_meta_async(
            real_async_db_session,
            async_test_household.id,
            NotificationDedupKey(
                meta_type='equipment_overdue', ref_key='assignment_id', ref_id='a-1'
            ),
            since=datetime.now(UTC) - timedelta(hours=1),
        )
        assert exists is False

    async def test_false_for_other_organization(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user: User,
    ):
        await self._make_notification(
            real_async_db_session,
            async_test_user.id,
            meta={'type': 'equipment_warranty', 'item_id': 'abc-123'},
        )
        exists = await NotificationService.exists_unread_by_meta_async(
            real_async_db_session,
            uuid.uuid4(),
            NotificationDedupKey(
                meta_type='equipment_warranty', ref_key='item_id', ref_id='abc-123'
            ),
            since=datetime.now(UTC) - timedelta(hours=1),
        )
        assert exists is False


@pytest.mark.integration
@pytest.mark.asyncio
class TestMarkReadByMetaAsync:
    """Clearing the unread notices about one record, inside one organization."""

    async def _add(
        self, db: AsyncSession, user_id: uuid.UUID, meta: dict[str, str]
    ) -> Notification:
        n = Notification(user_id=user_id, title='t', content='c', meta_data=meta)
        db.add(n)
        await db.flush()
        return n

    async def test_marks_only_the_matching_record_read(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user: User,
    ):
        db = real_async_db_session
        hit = await self._add(db, async_test_user.id, {'ref': 'r-1'})
        other = await self._add(db, async_test_user.id, {'ref': 'r-2'})

        changed = await NotificationService.mark_read_by_meta_async(
            db, async_test_household.id, 'ref', 'r-1'
        )

        await db.refresh(hit)
        await db.refresh(other)
        assert changed == 1
        assert hit.is_read is True
        assert other.is_read is False

    async def test_leaves_other_organizations_alone(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user: User,
    ):
        db = real_async_db_session
        n = await self._add(db, async_test_user.id, {'ref': 'r-1'})

        changed = await NotificationService.mark_read_by_meta_async(
            db, uuid.uuid4(), 'ref', 'r-1'
        )

        await db.refresh(n)
        assert changed == 0
        assert n.is_read is False


@pytest.mark.integration
@pytest.mark.asyncio
class TestFlushOnlyContract:
    """Notification mutations must not commit mid-transaction.

    The service contract is flush-only — the caller (or ``get_async_db``
    after the request) owns the commit. A regression to ``db.commit()``
    inside these methods would silently commit unrelated work sharing the
    transaction, so pin it with a commit spy.
    """

    async def test_update_notification_does_not_commit(
        self,
        async_db: AsyncSession,
        async_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notification = Notification(user_id=async_user.id, title='t', content='c')
        async_db.add(notification)
        await async_db.flush()

        commit_spy = AsyncMock()
        monkeypatch.setattr(async_db, 'commit', commit_spy)

        await NotificationService.update_notification_async(
            async_db, notification, True
        )

        commit_spy.assert_not_called()
        assert notification.is_read is True

    async def test_mark_all_read_does_not_commit(
        self,
        async_db: AsyncSession,
        async_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async_db.add_all(
            [
                Notification(user_id=async_user.id, title='t1', content='c1'),
                Notification(user_id=async_user.id, title='t2', content='c2'),
            ]
        )
        await async_db.flush()

        commit_spy = AsyncMock()
        monkeypatch.setattr(async_db, 'commit', commit_spy)

        await NotificationService.mark_all_read_async(async_db, async_user.id)

        commit_spy.assert_not_called()
        unread = await async_db.scalar(
            select(Notification).where(
                Notification.user_id == async_user.id,
                Notification.is_read.is_(False),
            )
        )
        assert unread is None

    async def test_delete_notification_does_not_commit(
        self,
        async_db: AsyncSession,
        async_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notification = Notification(user_id=async_user.id, title='t', content='c')
        async_db.add(notification)
        await async_db.flush()
        notification_id = notification.id

        commit_spy = AsyncMock()
        monkeypatch.setattr(async_db, 'commit', commit_spy)

        await NotificationService.delete_notification_async(async_db, notification)

        commit_spy.assert_not_called()
        assert await async_db.get(Notification, notification_id) is None
