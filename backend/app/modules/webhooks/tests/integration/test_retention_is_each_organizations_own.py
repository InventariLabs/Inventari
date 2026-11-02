"""Two organizations, two retention settings, one cleanup run.

The worker read `log_retention_days` from `orgs[0]` — whichever organization
the installation listed first — and then deleted across every organization,
with no filter at all. The settings schema promises each of them a number
between 1 and 365, so an organization that asked for a year lost its history
after thirty days, and one that asked for a week kept it for a year.

Invisible on an install with one organization, which is the only kind this was
ever watched on. Hence two here: the report was read from the code, and this is
the measurement it asked for.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.modules.webhooks import _webhook_workers as workers
from app.modules.webhooks._webhook_workers import (
    cleanup_logs_per_organization_async,
)
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint
from app.modules.webhooks.module import WebhooksModule

KEEPS_A_YEAR = 365
KEEPS_A_WEEK = 7


async def _org(db: AsyncSession, name: str, retention_days: int) -> Organization:
    org = Organization(
        name=f'{name} {uuid4().hex[:6]}',
        enabled_modules=['core', 'webhooks'],
        settings={'module:webhooks': {'log_retention_days': retention_days}},
    )
    db.add(org)
    await db.flush()
    return org


async def _log_aged(db: AsyncSession, org: Organization, days: int) -> None:
    endpoint = WebhookEndpoint(
        organization_id=org.id,
        name='Listener',
        url='https://example.com/hook',
        event_types=['item.created'],
        is_active=True,
    )
    db.add(endpoint)
    await db.flush()

    log = WebhookDeliveryLog(
        webhook_endpoint_id=endpoint.id,
        organization_id=org.id,
        event_type='item.created',
        payload_json={'event': 'item.created'},
        attempt_number=1,
        delivery_status='success',
        created_at=datetime.now(UTC) - timedelta(days=days),
    )
    db.add(log)
    await db.flush()


async def _rows_left(db: AsyncSession, org_id: UUID) -> int:
    result = await db.execute(
        select(WebhookDeliveryLog).where(WebhookDeliveryLog.organization_id == org_id)
    )
    return len(result.scalars().all())


@pytest.mark.asyncio
@pytest.mark.integration
async def test_each_organization_keeps_what_it_asked_for(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session

    patient = await _org(db, 'Keeps a year', KEEPS_A_YEAR)
    tidy = await _org(db, 'Keeps a week', KEEPS_A_WEEK)
    patient_id, tidy_id = patient.id, tidy.id

    # Old enough for the tidy one to drop and the patient one to keep. Under
    # the old worker whichever organization came first decided for both.
    await _log_aged(db, patient, days=60)
    await _log_aged(db, tidy, days=60)
    await db.commit()

    await cleanup_logs_per_organization_async(db)

    assert await _rows_left(db, patient_id) == 1
    assert await _rows_left(db, tidy_id) == 0


class _GlobalSessionContext:
    """The slice of the module context the cleanup worker opens a session on."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    @asynccontextmanager
    async def global_session(self) -> AsyncIterator[AsyncSession]:
        yield self._db


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_scheduled_worker_applies_each_organizations_retention(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    patient = await _org(db, 'Keeps a year', KEEPS_A_YEAR)
    tidy = await _org(db, 'Keeps a week', KEEPS_A_WEEK)
    patient_id, tidy_id = patient.id, tidy.id
    await _log_aged(db, patient, days=60)
    await _log_aged(db, tidy, days=60)
    await db.commit()

    module = WebhooksModule()
    module._context = cast(Any, _GlobalSessionContext(db))
    await module._cleanup_worker()

    assert await _rows_left(db, patient_id) == 1
    assert await _rows_left(db, tidy_id) == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_one_failing_organization_does_not_stop_the_others(
    real_async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = real_async_db_session
    broken = await _org(db, 'Cleanup breaks', KEEPS_A_WEEK)
    tidy = await _org(db, 'Keeps a week', KEEPS_A_WEEK)
    broken_id, tidy_id = broken.id, tidy.id
    await _log_aged(db, broken, days=60)
    await _log_aged(db, tidy, days=60)
    await db.commit()

    real_cleanup = workers.cleanup_old_logs

    async def failing_for_one(*args: Any, **kwargs: Any) -> int:
        if kwargs.get('organization_id') == broken_id:
            # A statement error, not a Python one: it aborts the transaction
            # the next organization is about to use.
            await db.execute(text('SELECT 1/0'))
        return await real_cleanup(*args, **kwargs)

    monkeypatch.setattr(workers, 'cleanup_old_logs', failing_for_one)

    with caplog.at_level('ERROR'):
        deleted = await workers.cleanup_logs_per_organization_async(db)

    assert deleted == 1
    assert await _rows_left(db, tidy_id) == 0, 'the next organization is still cleaned'
    assert await _rows_left(db, broken_id) == 1
    assert str(broken_id) in caplog.text, 'the failure names the organization'
