"""A purchase order mailed to a supplier leaves through the organization's server.

Settings → Email is "the SMTP server for invitations, purchase orders and
notifications", but only the account mails handed the organization's server
to the queue. A purchase order came without one, so the worker fell back to
the installation's own settings: on an installation with none it failed "SMTP
is not configured" while the organization's server stood ready, and on one
with a server the supplier got the order from the installation's address.
The test runs the durable ``email_jobs`` row through the real worker, with
nothing in the installation's settings.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.email_job import EmailJob
from app.services.email_jobs import process_email_jobs_batch
from tests.integration._shelf import run_in_async_session

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def production_queue_without_system_smtp(
    monkeypatch: pytest.MonkeyPatch, async_engine_fixture: AsyncEngine
) -> None:
    """Queue the mail the way production does, with no installation server.

    ``send_email_with_attachment_async`` sends directly under TESTING. The
    enqueuer opens its own session through ``db_facade``, which reads
    ``AsyncSessionLocal`` from ``app.database`` — pointed at the test database.
    """
    monkeypatch.setattr('app.services.email_service.settings.TESTING', False)
    monkeypatch.setattr('app.services.email_service.settings.INVENTARI_DEMO', False)
    for name in ('SMTP_HOST', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_ENCRYPTION'):
        monkeypatch.setattr(f'app.services.email_service.settings.{name}', None)
    monkeypatch.setattr(
        'app.database.AsyncSessionLocal',
        async_sessionmaker(
            async_engine_fixture, class_=AsyncSession, expire_on_commit=False
        ),
    )


def test_the_supplier_gets_the_order_through_the_organizations_relay(
    client: TestClient,
    po_auth_headers: dict[str, str],
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    po_org: Any,
    po_partner: Any,
    po_template: Any,
) -> None:
    po_org.settings = {
        'smtp': {'host': 'relay.example.test', 'port': 25, 'encryption': 'none'}
    }
    db_session.commit()
    created = client.post(
        '/api/v1/purchase-orders',
        headers=po_auth_headers,
        json={
            'partner_id': str(po_partner.id),
            'lines': [
                {
                    'product_template_id': str(po_template.id),
                    'quantity_ordered': 10,
                    'unit_price': '5.00',
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    po_id = created.json()['id']
    confirmed = client.post(
        f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

    sent = client.post(
        f'/api/v1/purchase-orders/{po_id}/send-email', headers=po_auth_headers
    )
    assert sent.status_code == status.HTTP_200_OK, sent.text

    async def _deliver(session: AsyncSession) -> EmailJob:
        job = (
            await session.execute(
                select(EmailJob).where(EmailJob.to_email == po_partner.email)
            )
        ).scalar_one()
        # The organization's server is stored with the row, as the account
        # mails store theirs, for whichever worker picks it up.
        assert job.smtp_config_enc is not None
        await process_email_jobs_batch(session)
        await session.refresh(job)
        return job

    smtp = MagicMock()
    with patch('smtplib.SMTP', smtp):
        job = run_in_async_session(async_engine_fixture, _deliver)

    assert smtp.call_args.args[:2] == ('relay.example.test', 25)
    smtp.return_value.__enter__.return_value.send_message.assert_called_once()
    assert job.status == 'sent', job.last_error
