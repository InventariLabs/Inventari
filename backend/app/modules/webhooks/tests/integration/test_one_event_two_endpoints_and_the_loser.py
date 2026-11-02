"""One event cutting two endpoints keeps the loser lost no longer.

One event fanned out to two falling endpoints races on the one AsyncSession
the dispatch shares: both probes cross the threshold together, and the
session work the cut-off does beside the tally (the audit journal and the
admin notification) interleaves — the loser's attribute history is reset
mid-flight, its failure never reaches the database, the endpoint that had
crossed the threshold stays ACTIVE with a diminished counter, and its
delivery row stays ``pending``, which the stale-pending requeue then picks
up and delivers the same event a second time.

This is the differentiating test for that defect: both probes answer in the
SAME event-loop tick (a rendezvous, not a stagger), so both coroutines sit
in the tally/cut-off phase overlapping the way two real receivers answering
at once put them. A staggered variant — the first revision of this file —
lets the loser finish its whole write before the other wakes, the phases
never overlap, and the test reads green on the defective tree; that green
measured the serialization, not the code.

The test reads the truth from a fresh session: the instances the dispatch
mutated carry their values in memory (expire_on_commit=False), so only a
session that never touched the fan-out can say what actually landed.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.database
from app.models.organization import Organization
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint

pytestmark = pytest.mark.integration

_REFUSED_URL = 'http://127.0.0.1:9/hook'  # closed port: the probe fails fast


def _payload(org_id: uuid.UUID) -> Any:
    from app.core.events import TenantEventPayload

    return TenantEventPayload(**{'organization_id': str(org_id), 'detail': 'x'})


@pytest.fixture
async def session_factory(
    async_engine_fixture: Any,
    setup_test_db: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> async_sessionmaker[AsyncSession]:
    factory = async_sessionmaker(
        async_engine_fixture, class_=AsyncSession, expire_on_commit=False
    )
    # The dispatch opens its own sessions through the module DB facade,
    # which forwards live to app.database.AsyncSessionLocal — point that
    # at the test engine.
    monkeypatch.setattr(app.database, 'AsyncSessionLocal', factory)
    return factory


async def _seed_two_falling_endpoints(
    factory: async_sessionmaker[AsyncSession], *, threshold: int = 3
) -> tuple[uuid.UUID, WebhookEndpoint, WebhookEndpoint]:
    async with factory() as session:
        org = Organization(name='Race Org', enabled_modules=['webhooks'])
        session.add(org)
        await session.flush()
        from app.core.public_api import core_api

        await core_api.settings.set_bulk_async(
            session, org.id, 'webhooks', {'circuit_breaker_threshold': threshold}
        )
        endpoints = [
            WebhookEndpoint(
                organization_id=org.id,
                name=f'Falling receiver {n}',
                url=_REFUSED_URL,
                http_method='POST',
                event_types=['item.created'],
                max_retries=0,
                retry_backoff_seconds=1,
                timeout_seconds=2,
                is_active=True,
                consecutive_failures=2,
            )
            for n in ('A', 'B')
        ]
        session.add_all(endpoints)
        await session.commit()
        return org.id, endpoints[0], endpoints[1]


@pytest.mark.integration
class TestOneEventTwoEndpointsAndTheLoser:
    async def test_the_breaker_cuts_every_endpoint_that_crossed_and_resolves_every_row(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        from app.core.events import SystemEvent
        from app.modules.webhooks import webhook_service

        org_id, endpoint_a, endpoint_b = await _seed_two_falling_endpoints(
            session_factory
        )

        probes: list[str] = []
        arrived = 0
        release = asyncio.Event()

        async def simultaneous_probe(
            webhook: WebhookEndpoint, *args: Any, **kwargs: Any
        ) -> tuple[bool, int | None, str | None, str | None]:
            # Both endpoints answer in the same tick: the second arrival
            # releases the first, so both coroutines leave the HTTP phase
            # together and their tally/cut-off phases overlap on the one
            # session — the window where the loser's history gets reset.
            nonlocal arrived
            probes.append(webhook.name)
            arrived += 1
            if arrived == 2:
                release.set()
            await release.wait()
            return (False, 500, 'boom', 'connection refused')

        with patch.object(
            webhook_service, '_attempt_delivery', side_effect=simultaneous_probe
        ):
            await webhook_service.dispatch_event(
                SystemEvent.ITEM_CREATED, _payload(org_id)
            )

        assert sorted(probes) == ['Falling receiver A', 'Falling receiver B']

        # The truth from a session that never touched the fan-out.
        async with session_factory() as fresh:
            for endpoint_id in (endpoint_a.id, endpoint_b.id):
                row = await fresh.get(WebhookEndpoint, endpoint_id)
                assert row is not None
                assert row.consecutive_failures == 3, (
                    f'{row.name}: the failure must reach the database — a '
                    'diminished counter leaves a cut-off endpoint active'
                )
                assert row.is_active is False, (
                    f'{row.name}: it crossed the threshold, the breaker cuts '
                    'it off with its peers, not only the first one home'
                )

            rows = (
                (
                    await fresh.execute(
                        select(WebhookDeliveryLog).where(
                            WebhookDeliveryLog.organization_id == org_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 2
            for log_row in rows:
                assert log_row.delivery_status != 'pending', (
                    'a failed attempt resolves its row (failed here — '
                    'max_retries=0); a row left pending is the stale-pending '
                    "requeue's third POST of the same event"
                )
                assert log_row.delivery_status == 'failed'

        # The requeue precondition is gone: a retry pass over the board
        # must not send anything — two probes, and no third one coming.
        from app.modules.webhooks._webhook_workers import retry_failed_deliveries

        async with session_factory() as session:
            await retry_failed_deliveries(session)
        assert sorted(probes) == ['Falling receiver A', 'Falling receiver B'], (
            'a row left pending comes back as a second delivery of the same '
            'event — the loser must not feed the requeue'
        )
