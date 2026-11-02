"""One threshold governs every probe the breaker counts.

The circuit-breaker counter is fed by three paths — the delivery, the
retry worker, and the Test button — and only the first used to hand it
the organization's configured threshold; retries and the Test button cut
off on the built-in default of ten, so the setting on screen chose a
policy for one probe in three. The threshold is now read where the
counter is updated, from the organization the endpoint belongs to, and
no caller can hand the breaker a different policy by omitting an
argument. A retry counts as its own probe: it is a real HTTP attempt,
and its failure lands on the same consecutive tally the first attempt
started.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.database
from app.models.organization import Organization
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint

pytestmark = pytest.mark.integration

_REFUSED_URL = 'http://127.0.0.1:9/hook'  # closed port: the probe fails fast


async def _seed_endpoint(
    session: AsyncSession, *, threshold: int, failures: int = 2
) -> tuple[Organization, WebhookEndpoint]:
    from app.core.public_api import core_api

    org = Organization(name='Probe Org', enabled_modules=['webhooks'])
    session.add(org)
    await session.flush()
    await core_api.settings.set_bulk_async(
        session, org.id, 'webhooks', {'circuit_breaker_threshold': threshold}
    )
    endpoint = WebhookEndpoint(
        organization_id=org.id,
        name='Probe receiver',
        url=_REFUSED_URL,
        http_method='POST',
        event_types=['item.created'],
        max_retries=3,
        retry_backoff_seconds=1,
        timeout_seconds=2,
        is_active=True,
        consecutive_failures=failures,
    )
    session.add(endpoint)
    await session.commit()
    return org, endpoint


class TestOneThresholdForEveryProbe:
    async def test_the_test_button_cuts_off_at_the_configured_threshold(
        self,
        async_engine_fixture: Any,
        setup_test_db: Any,
    ) -> None:
        from app.modules.webhooks.webhook_service import deliver_test_ping

        factory = async_sessionmaker(
            async_engine_fixture, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            org, endpoint = await _seed_endpoint(session, threshold=3)

            await deliver_test_ping(session, endpoint, str(org.id))
            await session.commit()

            assert endpoint.consecutive_failures == 3
            assert endpoint.is_active is False, (
                'the administrator set the breaker to three and the Test '
                'probe failed — the third cut-off cannot wait for ten'
            )

    async def test_a_retry_cuts_off_at_the_configured_threshold(
        self,
        async_engine_fixture: Any,
        setup_test_db: Any,
    ) -> None:
        from app.modules.webhooks._webhook_constants import (
            _DELIVERY_STATUS_PENDING_RETRY,
        )
        from app.modules.webhooks._webhook_workers import retry_failed_deliveries

        factory = async_sessionmaker(
            async_engine_fixture, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            org, endpoint = await _seed_endpoint(session, threshold=3)
            session.add(
                WebhookDeliveryLog(
                    webhook_endpoint_id=endpoint.id,
                    organization_id=org.id,
                    event_type='item.created',
                    payload_json={'event': 'item.created'},
                    attempt_number=1,
                    delivery_status=_DELIVERY_STATUS_PENDING_RETRY,
                    next_retry_at=datetime.now(UTC) - timedelta(seconds=5),
                )
            )
            await session.commit()

            await retry_failed_deliveries(session)

            assert endpoint.consecutive_failures == 3
            assert endpoint.is_active is False, (
                'retries carry real events to a falling endpoint — they cut '
                'off at the configured threshold, not at the built-in ten'
            )

    async def test_the_first_delivery_cuts_off_at_the_configured_threshold(
        self,
        async_engine_fixture: Any,
        setup_test_db: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.core.contracts.events import TenantEventPayload
        from app.modules.webhooks.webhook_service import dispatch_event

        factory = async_sessionmaker(
            async_engine_fixture, class_=AsyncSession, expire_on_commit=False
        )
        monkeypatch.setattr(app.database, 'AsyncSessionLocal', factory)
        async with factory() as session:
            org, endpoint = await _seed_endpoint(session, threshold=3)

            await dispatch_event(
                'item.created', TenantEventPayload(organization_id=str(org.id))
            )

            await session.refresh(endpoint)
            assert endpoint.consecutive_failures == 3
            assert endpoint.is_active is False

    async def test_one_dispatch_counts_on_every_endpoint_it_matches(
        self,
        async_engine_fixture: Any,
        setup_test_db: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Two receivers hear the same event; one dispatch tallies both.

        The dispatch shares one session across its concurrent deliveries,
        so the threshold has to travel down as a value read before the
        fan-out: a read beside the tally would put a query where two
        coroutines meet, every endpoint after the first would lose its
        attempt, and its delivery row would hang in flight until the
        retry worker sent the receiver a duplicate.
        """
        from sqlalchemy import select

        from app.core.contracts.events import TenantEventPayload
        from app.modules.webhooks._webhook_constants import (
            _DELIVERY_STATUS_PENDING,
            _DELIVERY_STATUS_PENDING_RETRY,
        )
        from app.modules.webhooks.webhook_service import dispatch_event

        factory = async_sessionmaker(
            async_engine_fixture, class_=AsyncSession, expire_on_commit=False
        )
        monkeypatch.setattr(app.database, 'AsyncSessionLocal', factory)
        async with factory() as session:
            org, endpoint = await _seed_endpoint(session, threshold=3, failures=0)
            second = WebhookEndpoint(
                organization_id=org.id,
                name='Second receiver',
                url=_REFUSED_URL,
                http_method='POST',
                event_types=['item.created'],
                max_retries=0,
                retry_backoff_seconds=1,
                timeout_seconds=2,
                is_active=True,
                consecutive_failures=0,
            )
            endpoint.max_retries = 0
            session.add(second)
            await session.commit()

            await dispatch_event(
                'item.created', TenantEventPayload(organization_id=str(org.id))
            )

            await session.refresh(endpoint)
            await session.refresh(second)
            assert endpoint.consecutive_failures == 1
            assert second.consecutive_failures == 1, (
                'both endpoints match the event — the second delivery '
                'shares the session and must still reach the tally'
            )
            rows = (
                (
                    await session.execute(
                        select(WebhookDeliveryLog).where(
                            WebhookDeliveryLog.organization_id == org.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 2
            for row in rows:
                assert row.delivery_status not in (
                    _DELIVERY_STATUS_PENDING,
                    _DELIVERY_STATUS_PENDING_RETRY,
                ), (
                    'a row left in flight would be requeued and the '
                    'receiver would get the same event twice'
                )
