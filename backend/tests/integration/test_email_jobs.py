"""Integration tests for the durable email queue.

- A queued job is sent exactly once (claim-then-send, SKIP LOCKED).
- An SMTP failure reschedules the job with backoff.
- A poison job is marked FAILED after max_attempts.
- A crashed in-flight job (stale 'sending') is reclaimed.
- smtp_config overrides are stored Fernet-encrypted, never plaintext.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.email_job import EmailJob
from app.services.email_jobs import enqueue_email_job, process_email_jobs_batch

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def smtp_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """State the SMTP settings the worker sends with, rather than inherit them.

    Without this the sender refused every message on ``is_configured`` and
    returned before it ever reached the patched ``smtplib.SMTP`` — so the
    outcome depended on whether the machine's ``.env`` happened to point at
    mailhog, and the two failure tests below passed for the wrong reason:
    they proved "no server configured" reschedules, not "the server refused".
    The port is left out of the encryption decision on purpose.
    """
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


def _mock_smtp(ok: bool = True) -> MagicMock:
    server = MagicMock()
    if not ok:
        import smtplib

        server.login.side_effect = smtplib.SMTPException('relay denied')
    smtp_cls = MagicMock()
    smtp_cls.return_value.__enter__.return_value = server
    return smtp_cls


async def _add_job(session_factory: SessionFactory, **overrides: Any) -> uuid.UUID:
    defaults: dict[str, Any] = {
        'to_email': 'user@example.com',
        'subject': 'Hello',
        'html_content': '<p>hi</p>',
        'status': 'pending',
        'next_attempt_at': datetime.now(UTC) - timedelta(seconds=1),
    }
    defaults.update(overrides)
    async with session_factory() as session:
        job = EmailJob(**defaults)
        session.add(job)
        await session.commit()
        return cast(uuid.UUID, job.id)


async def _fetch(session_factory: SessionFactory, job_id: uuid.UUID) -> EmailJob:
    async with session_factory() as session:
        job = await session.get(EmailJob, job_id)
        assert job is not None
        session.expunge(job)
        return job


@pytest.mark.integration
class TestEmailJobWorker:
    async def test_job_sent_exactly_once(self, session_factory: SessionFactory) -> None:
        job_id = await _add_job(session_factory)
        smtp_cls = _mock_smtp(ok=True)

        with patch('smtplib.SMTP', smtp_cls):
            async with session_factory() as session:
                sent = await process_email_jobs_batch(session)

        assert sent == 1
        smtp_cls.return_value.__enter__.return_value.send_message.assert_called_once()
        job = await _fetch(session_factory, job_id)
        assert job.status == 'sent'
        assert job.sent_at is not None
        assert job.attempts == 1

        # Second batch: nothing left to send.
        with patch('smtplib.SMTP', smtp_cls):
            async with session_factory() as session:
                sent_again = await process_email_jobs_batch(session)
        assert sent_again == 0
        smtp_cls.return_value.__enter__.return_value.send_message.assert_called_once()

    async def test_smtp_failure_reschedules_with_backoff(
        self, session_factory: SessionFactory
    ) -> None:
        job_id = await _add_job(session_factory)
        smtp_cls = _mock_smtp(ok=False)

        with patch('smtplib.SMTP', smtp_cls):
            async with session_factory() as session:
                sent = await process_email_jobs_batch(session)

        assert sent == 0
        # The reschedule has to be the answer to a refusal: without this the
        # test also passes when no SMTP server was configured at all.
        smtp_cls.return_value.__enter__.return_value.login.assert_called_once()
        job = await _fetch(session_factory, job_id)
        assert job.status == 'pending'
        assert job.attempts == 1
        assert job.next_attempt_at > datetime.now(UTC)
        # The row carries what the relay said, not what the queue decided:
        # the administrator reading it has to be able to tell a wrong
        # password from a closed port.
        assert job.last_error is not None
        assert 'relay denied' in job.last_error

    async def test_poison_job_fails_after_max_attempts(
        self, session_factory: SessionFactory
    ) -> None:
        job_id = await _add_job(session_factory, max_attempts=1)
        smtp_cls = _mock_smtp(ok=False)

        with patch('smtplib.SMTP', smtp_cls):
            async with session_factory() as session:
                sent = await process_email_jobs_batch(session)

        assert sent == 0
        smtp_cls.return_value.__enter__.return_value.login.assert_called_once()
        job = await _fetch(session_factory, job_id)
        assert job.status == 'failed'
        # A job that gave up still names the cause. 'max attempts reached'
        # describes the queue's own bookkeeping and leaves the reader with
        # nothing to act on.
        assert job.last_error is not None
        assert 'relay denied' in job.last_error

    async def test_crashed_in_flight_job_is_reclaimed(
        self, session_factory: SessionFactory
    ) -> None:
        job_id = await _add_job(
            session_factory,
            status='sending',
            claimed_at=datetime.now(UTC) - timedelta(minutes=30),
        )
        smtp_cls = _mock_smtp(ok=True)

        with patch('smtplib.SMTP', smtp_cls):
            async with session_factory() as session:
                sent = await process_email_jobs_batch(session)

        assert sent == 1
        job = await _fetch(session_factory, job_id)
        assert job.status == 'sent'

    async def test_fresh_in_flight_job_not_reclaimed(
        self, session_factory: SessionFactory
    ) -> None:
        job_id = await _add_job(
            session_factory, status='sending', claimed_at=datetime.now(UTC)
        )
        smtp_cls = _mock_smtp(ok=True)

        with patch('smtplib.SMTP', smtp_cls):
            async with session_factory() as session:
                sent = await process_email_jobs_batch(session)

        assert sent == 0
        smtp_cls.return_value.__enter__.return_value.send_message.assert_not_called()
        job = await _fetch(session_factory, job_id)
        assert job.status == 'sending'

    async def test_attachment_job_uses_attachment_sender(
        self, session_factory: SessionFactory
    ) -> None:
        job_id = await _add_job(
            session_factory,
            attachment_bytes=b'%PDF-1.4 fake',
            attachment_filename='protocol.pdf',
        )
        smtp_cls = _mock_smtp(ok=True)

        with patch('smtplib.SMTP', smtp_cls):
            async with session_factory() as session:
                sent = await process_email_jobs_batch(session)

        assert sent == 1
        # The name of this test claims the attachment sender ran; only that
        # path attaches a file, so the message itself has to say so.
        server = smtp_cls.return_value.__enter__.return_value
        server.send_message.assert_called_once()
        msg = server.send_message.call_args.args[0]
        assert 'protocol.pdf' in [part.get_filename() for part in msg.walk()]
        job = await _fetch(session_factory, job_id)
        assert job.status == 'sent'


@pytest.mark.integration
class TestEnqueueEmailJob:
    async def test_enqueue_persists_job_with_encrypted_smtp_config(
        self, session_factory: SessionFactory
    ) -> None:
        with patch('app.core.db_facade.AsyncSessionLocal', session_factory):
            job_id = await enqueue_email_job(
                'user@example.com',
                'Subject',
                '<p>body</p>',
                smtp_config={'host': 'smtp.x.com', 'password': 'super-secret'},
            )

        assert job_id is not None
        job = await _fetch(session_factory, job_id)
        assert job.status == 'pending'
        assert job.smtp_config_enc is not None
        assert 'super-secret' not in job.smtp_config_enc
        assert job.smtp_config_enc.startswith('enc:')

        # The worker decrypts it back to the original dict.
        from app.services.email_jobs import _decode_smtp_config

        decoded = _decode_smtp_config(job)
        assert decoded == {'host': 'smtp.x.com', 'password': 'super-secret'}
