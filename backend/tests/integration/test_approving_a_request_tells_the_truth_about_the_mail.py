"""Approving an access request says whether the link went out, and never loses it.

On an install with no mail server the approval answered ``email_sent: true``
because the queue accepted the row, and the row then failed after its retries:
the toast said the link was mailed, nothing arrived, and the one copy of the
token was gone with the request. The invitation path already hands the link
to the administrator when the organization sends no mail; approval now does
the same, and a delivery that fails later reaches the administrator who
approved, carrying the link.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.testing import ModuleTestHelper
from app.models.email_job import EmailJob
from app.models.notification import Notification
from app.models.organization import Organization
from app.services.email_jobs import enqueue_email_job, process_email_jobs_batch
from app.services.token_service import create_access_token

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

SessionFactory = async_sessionmaker[AsyncSession]


def _auth(user: Any) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture(autouse=True)
def production_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    """The TESTING fast-path sends directly; these tests are about the queue."""
    monkeypatch.setattr('app.services.email_service.settings.TESTING', False)


def _smtp(monkeypatch: pytest.MonkeyPatch, *, configured: bool) -> None:
    for name, value in (
        ('SMTP_HOST', 'smtp.test.invalid' if configured else ''),
        ('SMTP_PORT', 587),
        ('SMTP_USER', 'queue@test.invalid' if configured else ''),
        ('SMTP_PASSWORD', 'secret' if configured else ''),
    ):
        monkeypatch.setattr(f'app.services.email_service.settings.{name}', value)


async def _approve(client: Any, db: AsyncSession, user: Any) -> Any:
    user.is_superuser = True
    await db.commit()
    email = f'wanted-{uuid.uuid4().hex[:8]}@example.com'
    await client.post(
        '/api/v1/auth/registration-request',
        json={'email': email, 'full_name': 'Wanted', 'preferred_language': 'en'},
    )
    listed = await client.get('/api/v1/auth/registration-requests', headers=_auth(user))
    request_id = next(r['id'] for r in listed.json()['items'] if r['email'] == email)
    return await client.post(
        f'/api/v1/auth/registration-requests/{request_id}/approve',
        headers=_auth(user),
    )


class TestTheApprovalAnswer:
    async def test_without_a_mail_server_the_link_is_handed_over_not_mailed(
        self, real_async_client, real_async_db_session, async_test_user, monkeypatch
    ):
        _smtp(monkeypatch, configured=False)
        enqueue = AsyncMock(return_value=uuid.uuid4())

        with patch('app.services.email_jobs.enqueue_email_job', enqueue):
            response = await _approve(
                real_async_client, real_async_db_session, async_test_user
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['email_sent'] is False
        assert (
            body['registration_link'] == f'/register?token={body["registration_token"]}'
        )
        enqueue.assert_not_called()

    async def test_with_a_mail_server_the_queue_gets_the_link_and_a_failure_notice(
        self, real_async_client, real_async_db_session, async_test_user, monkeypatch
    ):
        _smtp(monkeypatch, configured=True)
        enqueue = AsyncMock(return_value=uuid.uuid4())

        with patch('app.services.email_jobs.enqueue_email_job', enqueue):
            response = await _approve(
                real_async_client, real_async_db_session, async_test_user
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['email_sent'] is True
        enqueue.assert_awaited_once()
        notice = enqueue.await_args.kwargs['failure_notice']
        assert notice['user_id'] == str(async_test_user.id)
        assert body['registration_link'] in notice['content']
        assert notice['link'] == '/settings'


@pytest.fixture
async def session_factory(
    async_engine_fixture: Any, setup_test_db: Any
) -> SessionFactory:
    factory = async_sessionmaker(
        async_engine_fixture, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        await session.execute(text('TRUNCATE email_jobs RESTART IDENTITY CASCADE'))
        await session.commit()
    return factory


def _refusing_smtp() -> MagicMock:
    import smtplib

    server = MagicMock()
    server.login.side_effect = smtplib.SMTPException('relay denied')
    smtp_cls = MagicMock()
    smtp_cls.return_value.__enter__.return_value = server
    return smtp_cls


class TestADeliveryThatFailsInTheQueue:
    async def _admin(self, factory: SessionFactory) -> uuid.UUID:
        async with factory() as session:
            org = Organization(
                name=f'Org {uuid.uuid4().hex[:6]}', enabled_modules=['core']
            )
            session.add(org)
            await session.flush()
            user = await ModuleTestHelper.create_user_async(
                session, org, email=f'approver-{uuid.uuid4().hex[:8]}@test.com'
            )
            await session.commit()
            return user.id

    async def _run_failing(
        self, factory: SessionFactory, notice: dict[str, Any] | None
    ) -> uuid.UUID:
        job_id = await enqueue_email_job(
            'wanted@example.com',
            'Registration',
            '<p>link</p>',
            max_attempts=1,
            failure_notice=notice,
        )
        assert job_id is not None
        with patch('smtplib.SMTP', _refusing_smtp()):
            async with factory() as session:
                await process_email_jobs_batch(session)
        return job_id

    @pytest.fixture(autouse=True)
    def _smtp_on(self, monkeypatch):
        _smtp(monkeypatch, configured=True)

    @pytest.fixture(autouse=True)
    def _queue_db(self, session_factory, monkeypatch):
        # Patched where the facade reads it, not on the facade (see the queue's
        # sibling tests): the enqueuer opens its own short session.
        monkeypatch.setattr('app.database.AsyncSessionLocal', session_factory)

    async def test_the_approving_administrator_gets_a_notification_with_the_link(
        self, session_factory: SessionFactory
    ):
        admin_id = await self._admin(session_factory)
        notice = {
            'user_id': str(admin_id),
            'title': 'Registration link not delivered',
            'content': 'Send wanted@example.com this link: http://app/register?token=abc',
            'link': '/settings',
        }

        job_id = await self._run_failing(session_factory, notice)

        async with session_factory() as session:
            job = await session.get(EmailJob, job_id)
            assert job is not None and job.status == 'failed'
            rows = (
                (
                    await session.execute(
                        select(Notification).where(Notification.user_id == admin_id)
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 1
        assert rows[0].type == 'error'
        assert 'register?token=abc' in rows[0].content
        assert rows[0].link == '/settings'

    async def test_a_retry_that_is_still_pending_notifies_nobody(
        self, session_factory: SessionFactory
    ):
        admin_id = await self._admin(session_factory)
        job_id = await enqueue_email_job(
            'wanted@example.com',
            'Registration',
            '<p>link</p>',
            max_attempts=5,
            failure_notice={
                'user_id': str(admin_id),
                'title': 't',
                'content': 'c',
                'link': '/settings',
            },
        )
        with patch('smtplib.SMTP', _refusing_smtp()):
            async with session_factory() as session:
                await process_email_jobs_batch(session)

        async with session_factory() as session:
            job = await session.get(EmailJob, job_id)
            assert job is not None and job.status == 'pending'
            count = (
                await session.execute(
                    select(Notification).where(Notification.user_id == admin_id)
                )
            ).all()
        assert count == []

    async def test_a_mail_that_carries_no_notice_fails_as_before(
        self, session_factory: SessionFactory
    ):
        job_id = await self._run_failing(session_factory, None)

        async with session_factory() as session:
            job = await session.get(EmailJob, job_id)
            assert job is not None and job.status == 'failed'
            assert job.failure_notice_enc is None
