"""The account mails ride the durable queue, not a bare SMTP socket.

Registration links, invitations and password resets used to send
directly — offloaded to a thread, one refused SMTP connection and the
mail was gone while the caller still reported success. The exact class
of mail whose loss hurts most had the least protection behind it. They
now enqueue ``email_jobs`` rows like every other mail, so an outage
retries instead of stranding the recipient.
"""

import smtplib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.email_job import EmailJob
from app.services.email_jobs import process_email_jobs_batch
from app.services.email_service import EmailService

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def production_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn the TESTING fast-path off, the way production runs.

    ``send_email_async`` keeps a direct send under TESTING so suites can
    assert delivery synchronously; these tests are about the queue, and
    would pass vacuously with the fast-path on.
    """
    monkeypatch.setattr('app.services.email_service.settings.TESTING', False)


@pytest.fixture(autouse=True)
def smtp_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """State the SMTP settings, rather than inherit the machine's .env."""
    for name, value in (
        ('SMTP_HOST', 'smtp.test.invalid'),
        ('SMTP_PORT', 587),
        ('SMTP_ENCRYPTION', 'starttls'),
        ('SMTP_USER', 'queue@test.invalid'),
        ('SMTP_PASSWORD', 'secret'),
    ):
        monkeypatch.setattr(f'app.services.email_service.settings.{name}', value)


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


@pytest.fixture(autouse=True)
def queue_db(session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """The enqueuer opens its own short session through db_facade; point
    that at the test engine.

    Patched where the facade reads it, not on the facade. db_facade forwards
    through a module ``__getattr__``, and monkeypatch restores by *setting*
    the value it read — which leaves a real attribute behind, shadowing the
    forward for the rest of the worker. Every later test that patched
    ``app.database`` then measured nothing.
    """
    monkeypatch.setattr('app.database.AsyncSessionLocal', session_factory)


async def _jobs(session_factory: SessionFactory) -> list[EmailJob]:
    async with session_factory() as session:
        rows = (
            (await session.execute(select(EmailJob).order_by(EmailJob.created_at)))
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
        return list(rows)


@pytest.mark.integration
class TestAccountMailsRideTheQueue:
    async def test_an_smtp_outage_at_invitation_time_leaves_a_retryable_job(
        self, session_factory: SessionFactory
    ) -> None:
        org_id = uuid.uuid4()

        # Inviting succeeds the moment the job is accepted. No SMTP socket
        # is touched: the mock stays uncalled while the caller gets True.
        with patch('smtplib.SMTP', MagicMock()):
            ok = await EmailService.send_invitation_async(
                'newcomer@example.com',
                '/join?code=abc123',
                organization_name='Acme Farm',
                role='member',
                lang='en',
                organization_id=org_id,
            )

        assert ok is True
        jobs = await _jobs(session_factory)
        assert len(jobs) == 1
        job = jobs[0]
        assert job.to_email == 'newcomer@example.com'
        assert job.status == 'pending'
        assert job.organization_id == org_id

        # The outage: the worker's first attempt is refused. The job stays
        # scheduled for another try — this is the difference from the old
        # direct send, which dropped the invitation on the same refusal.
        failing = MagicMock()
        failing.return_value.__enter__.return_value.login.side_effect = (
            smtplib.SMTPException('relay denied')
        )
        with patch('smtplib.SMTP', failing):
            async with session_factory() as session:
                sent = await process_email_jobs_batch(session)

        assert sent == 0
        failing.return_value.__enter__.return_value.login.assert_called_once()
        job = (await _jobs(session_factory))[0]
        assert job.status == 'pending'
        assert job.attempts == 1
        assert job.next_attempt_at > datetime.now(UTC)

        # The backoff window elapses.
        async with session_factory() as session:
            queued = await session.get(EmailJob, job.id)
            assert queued is not None
            queued.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

        # And the recovery: when the relay answers again, the same job
        # delivers — the invitee is not re-invited by hand.
        healthy = MagicMock()
        with patch('smtplib.SMTP', healthy):
            async with session_factory() as session:
                sent = await process_email_jobs_batch(session)

        assert sent == 1
        job = (await _jobs(session_factory))[0]
        assert job.status == 'sent'
        assert job.attempts == 2

    async def test_registration_link_and_password_reset_queue_too(
        self, session_factory: SessionFactory
    ) -> None:
        org_id = uuid.uuid4()
        with patch('smtplib.SMTP', MagicMock()):
            ok_registration = await EmailService.send_registration_link_async(
                'joiner@example.com', '/register?token=xyz'
            )
            ok_reset = await EmailService.send_password_reset_email_async(
                'locked-out@example.com',
                '/reset-password/tok',
                organization_id=org_id,
            )

        assert ok_registration is True
        assert ok_reset is True

        jobs = await _jobs(session_factory)
        assert {job.to_email for job in jobs} == {
            'joiner@example.com',
            'locked-out@example.com',
        }
        reset = next(job for job in jobs if job.to_email == 'locked-out@example.com')
        assert reset.organization_id == org_id
        assert reset.status == 'pending'
