"""A password-reset mail leaves through the organization's own mail server.

The request endpoint hands the organization's SMTP settings to the mail
queue. The job a worker picks up later has only what was stored with it:
without those settings it falls back to the installation's own, finds them
empty and fails "SMTP is not configured" on an install that sends every
other mail. The sibling test in ``test_password_reset.py`` intercepts
``send_email_async`` and so proves the hand-over; this one runs the durable
``email_jobs`` row through the real worker and proves delivery.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.email_job import EmailJob
from app.services.email_jobs import process_email_jobs_batch


@pytest.fixture(autouse=True)
def production_queue_without_system_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the queue the way production does, with nothing in the system SMTP.

    ``send_email_async`` keeps a direct send under TESTING, which would pass
    without a queue at all.
    """
    monkeypatch.setattr('app.services.email_service.settings.TESTING', False)
    monkeypatch.setattr('app.services.email_service.settings.INVENTARI_DEMO', False)
    for name in ('SMTP_HOST', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_ENCRYPTION'):
        monkeypatch.setattr(f'app.services.email_service.settings.{name}', None)


@pytest.mark.integration
class TestPasswordResetMailLeavesThroughTheOrganizationsServer:
    async def test_the_queued_job_delivers_through_the_organizations_relay(
        self,
        real_async_client,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_household,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The enqueuer opens its own short session through db_facade, which
        # reads ``AsyncSessionLocal`` from ``app.database`` — point that at the
        # test database (see test_account_mails_ride_the_queue.py).
        factory = async_sessionmaker(
            real_async_db_session.bind, class_=AsyncSession, expire_on_commit=False
        )
        monkeypatch.setattr('app.database.AsyncSessionLocal', factory)
        async_test_household.settings = {
            'smtp': {'host': 'relay.example.test', 'port': 25, 'encryption': 'none'}
        }
        await real_async_db_session.commit()

        response = await real_async_client.post(
            '/api/v1/auth/password-reset/request',
            json={'email': async_test_user.email},
        )
        assert response.status_code == 202

        # The request only queued the mail, with the organization's server
        # stored encrypted on the row for the worker to find.
        async with factory() as session:
            job = (
                await session.execute(
                    select(EmailJob).where(EmailJob.to_email == async_test_user.email)
                )
            ).scalar_one()
            assert job.status == 'pending'
            assert job.smtp_config_enc is not None
            job_id = job.id

        smtp = MagicMock()
        with patch('smtplib.SMTP', smtp):
            async with factory() as session:
                await process_email_jobs_batch(session)

        assert smtp.call_args.args[:2] == ('relay.example.test', 25)
        smtp.return_value.__enter__.return_value.send_message.assert_called_once()
        async with factory() as session:
            sent = await session.get(EmailJob, job_id)
            assert sent is not None
            assert sent.status == 'sent'
