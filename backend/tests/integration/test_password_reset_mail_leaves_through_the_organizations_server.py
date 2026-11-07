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

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.email_job import EmailJob
from app.services.email_jobs import process_email_jobs_batch

SessionFactory = async_sessionmaker[AsyncSession]


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
def production_queue_without_system_smtp(
    session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run the queue the way production does, with nothing in the system SMTP.

    ``send_email_async`` keeps a direct send under TESTING, which would pass
    without a queue at all. The enqueuer opens its own session through
    ``db_facade``; the facade reads ``AsyncSessionLocal`` from ``app.database``
    (see ``test_account_mails_ride_the_queue.py`` on why it is patched there).
    """
    monkeypatch.setattr('app.services.email_service.settings.TESTING', False)
    monkeypatch.setattr('app.database.AsyncSessionLocal', session_factory)
    for name in ('SMTP_HOST', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_ENCRYPTION'):
        monkeypatch.setattr(f'app.services.email_service.settings.{name}', None)
    monkeypatch.setattr('app.services.email_service.settings.INVENTARI_DEMO', False)


@pytest.mark.integration
class TestPasswordResetMailLeavesThroughTheOrganizationsServer:
    async def test_the_queued_job_delivers_through_the_organizations_relay(
        self,
        client: TestClient,
        test_user,
        test_household,
        db_session,
        session_factory: SessionFactory,
    ) -> None:
        test_household.settings = {
            'smtp': {'host': 'relay.example.test', 'port': 25, 'encryption': 'none'}
        }
        db_session.commit()

        response = client.post(
            '/api/v1/auth/password-reset/request',
            json={'email': test_user.email},
        )
        assert response.status_code == 202

        # The request only queued the mail, with the organization's server
        # stored encrypted on the row for the worker to find.
        async with session_factory() as session:
            job = (await session.execute(select(EmailJob))).scalar_one()
            assert job.to_email == test_user.email
            assert job.status == 'pending'
            assert job.smtp_config_enc is not None

        smtp = MagicMock()
        with patch('smtplib.SMTP', smtp):
            async with session_factory() as session:
                sent = await process_email_jobs_batch(session)

        assert sent == 1
        assert smtp.call_args.args[:2] == ('relay.example.test', 25)
        smtp.return_value.__enter__.return_value.send_message.assert_called_once()
        async with session_factory() as session:
            job = (await session.execute(select(EmailJob))).scalar_one()
            assert job.status == 'sent'
