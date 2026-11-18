"""The daily retention run trims what nothing needs any more, and only that.

Each table has rows that must survive however old they are: an event the relay
has not published yet, mail still waiting for its turn. The tests pin both
sides of every window, because a purge that deletes too little is a slow leak
and one that deletes too much loses work.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app._lifespan import _register_background_jobs
from app.config import settings
from app.models.email_job import EmailJob
from app.models.event_outbox import EventOutbox
from app.models.notification import Notification
from app.models.user import User
from app.services import table_retention
from app.services._org_membership import INVITE_RETENTION, INVITE_TTL
from app.services.table_retention import (
    purge_finished_email_jobs,
    purge_old_notifications,
    purge_published_outbox,
    run_table_retention_once,
)

pytestmark = pytest.mark.integration


def _days_ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


async def _ids(db: AsyncSession, model: Any) -> set[uuid.UUID]:
    return set((await db.scalars(select(model.id))).all())


def _event(**overrides: Any) -> EventOutbox:
    return EventOutbox(
        **{'id': uuid.uuid4(), 'event': 'item.moved', 'payload': {}, **overrides}
    )


def _mail(**overrides: Any) -> EmailJob:
    return EmailJob(
        **{
            'id': uuid.uuid4(),
            'to_email': 'someone@example.com',
            'subject': 'Hello',
            'html_content': '<p>hi</p>',
            **overrides,
        }
    )


def _notice(user_id: uuid.UUID, **overrides: Any) -> Notification:
    return Notification(
        **{
            'id': uuid.uuid4(),
            'user_id': user_id,
            'title': 'Title',
            'content': 'Content',
            **overrides,
        }
    )


class TestTheOutboxKeepsOnlyWhatStillMatters:
    async def test_a_row_published_before_the_window_goes(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        days = settings.EVENT_OUTBOX_RETENTION_DAYS
        expired = _event(published_at=_days_ago(days + 1))
        kept = _event(published_at=_days_ago(days - 1))
        db.add_all([expired, kept])
        await db.commit()
        kept_id = kept.id

        assert await purge_published_outbox(db) == 1

        assert await _ids(db, EventOutbox) == {kept_id}

    async def test_an_unpublished_row_stays_however_old_it_is(
        self, real_async_db_session: AsyncSession
    ) -> None:
        """It is an event the relay still owes the stream."""
        db = real_async_db_session
        waiting = _event(created_at=_days_ago(400), published_at=None)
        db.add(waiting)
        await db.commit()
        waiting_id = waiting.id

        assert await purge_published_outbox(db) == 0

        assert await _ids(db, EventOutbox) == {waiting_id}

    async def test_the_window_is_the_configured_one(
        self, real_async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, 'EVENT_OUTBOX_RETENTION_DAYS', 1)
        db = real_async_db_session
        db.add(_event(published_at=_days_ago(2)))
        await db.commit()

        assert await purge_published_outbox(db) == 1


class TestTheMailQueueForgetsFinishedMail:
    @pytest.mark.parametrize('status', ['sent', 'failed'])
    async def test_finished_mail_past_the_window_goes(
        self, real_async_db_session: AsyncSession, status: str
    ) -> None:
        db = real_async_db_session
        days = settings.EMAIL_JOB_RETENTION_DAYS
        expired = _mail(status=status, created_at=_days_ago(days + 1))
        kept = _mail(status=status, created_at=_days_ago(days - 1))
        db.add_all([expired, kept])
        await db.commit()
        kept_id = kept.id

        assert await purge_finished_email_jobs(db) == 1

        assert await _ids(db, EmailJob) == {kept_id}

    @pytest.mark.parametrize('status', ['pending', 'sending'])
    async def test_mail_still_on_its_way_stays(
        self, real_async_db_session: AsyncSession, status: str
    ) -> None:
        db = real_async_db_session
        waiting = _mail(status=status, created_at=_days_ago(400))
        db.add(waiting)
        await db.commit()
        waiting_id = waiting.id

        assert await purge_finished_email_jobs(db) == 0

        assert await _ids(db, EmailJob) == {waiting_id}

    def test_the_default_outlives_every_invitation_the_screen_can_show(self) -> None:
        """The invitation list reads how its mail ended from this table.

        A dead invitation stays on screen for ``INVITE_RETENTION`` past its
        expiry; a shorter window would blank the delivery state of rows the
        administrator can still see.
        """
        field = type(settings).model_fields['EMAIL_JOB_RETENTION_DAYS']

        assert timedelta(days=field.default) >= INVITE_TTL + INVITE_RETENTION


class TestTheBellForgetsOldNotifications:
    async def test_each_notification_goes_by_the_window_of_its_state(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        db = real_async_db_session
        user_id = async_test_user.id
        read_days = settings.NOTIFICATION_READ_RETENTION_DAYS
        unread_days = settings.NOTIFICATION_UNREAD_RETENTION_DAYS
        read_expired = _notice(
            user_id, is_read=True, created_at=_days_ago(read_days + 1)
        )
        read_kept = _notice(user_id, is_read=True, created_at=_days_ago(read_days - 1))
        # Past the window for read ones: nobody has seen it yet, so it stays.
        unread_kept = _notice(
            user_id, is_read=False, created_at=_days_ago(read_days + 1)
        )
        unread_expired = _notice(
            user_id, is_read=False, created_at=_days_ago(unread_days + 1)
        )
        db.add_all([read_expired, read_kept, unread_kept, unread_expired])
        await db.commit()
        kept = {read_kept.id, unread_kept.id}

        assert await purge_old_notifications(db) == 2

        assert await _ids(db, Notification) == kept


class TestTheRun:
    async def test_a_backlog_larger_than_one_batch_is_cleared_in_one_run(
        self, real_async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The first run on an old install meets years of rows at once."""
        monkeypatch.setattr(table_retention, '_BATCH_SIZE', 2)
        db = real_async_db_session
        db.add_all([_event(published_at=_days_ago(400)) for _ in range(5)])
        await db.commit()

        assert await purge_published_outbox(db) == 5

        assert await _ids(db, EventOutbox) == set()

    async def test_one_table_failing_leaves_the_others_trimmed(
        self,
        real_async_db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = real_async_db_session
        db.add(_event(published_at=_days_ago(400)))
        await db.commit()
        factory = async_sessionmaker(db.bind, expire_on_commit=False)
        monkeypatch.setattr('app.core.db_facade.AsyncSessionLocal', factory)
        broken = AsyncMock(side_effect=RuntimeError('boom'))
        monkeypatch.setattr(
            table_retention,
            '_PURGES',
            (('email_jobs', broken), ('event_outbox', purge_published_outbox)),
        )

        await run_table_retention_once()

        broken.assert_awaited_once()
        assert await _ids(db, EventOutbox) == set()

    def test_it_is_scheduled_daily_with_or_without_redis(self) -> None:
        scheduler = MagicMock()
        scheduler._redis = None
        bus = MagicMock()
        bus.redis = None

        _register_background_jobs(scheduler, bus)

        registered = {
            call.kwargs['name']: call.kwargs for call in scheduler.register.mock_calls
        }
        assert registered['table_retention']['interval'] == timedelta(hours=24)
        assert registered['table_retention']['handler'] is run_table_retention_once
