"""Integration tests for the webhook retry worker (claim-then-deliver).

The worker must not hold row locks across HTTP calls: it claims a batch in a
short transaction (status -> retrying + claimed_at), delivers outside the
lock, and commits the result per row. Stale claims (crashed worker) are
reclaimed.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.organization import Organization
from app.modules.webhooks._webhook_constants import (
    _ABANDON_CIRCUIT_BREAKER,
    _ABANDON_MODULE_DISABLED,
    _ABANDON_WEBHOOK_DISABLED,
    _DELIVERY_STATUS_FAILED,
    _DELIVERY_STATUS_PENDING_RETRY,
    _DELIVERY_STATUS_SUCCESS,
)
from app.modules.webhooks._webhook_workers import retry_failed_deliveries
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint

TABLES = 'webhook_delivery_logs, webhook_endpoints, organizations'

SessionFactory = async_sessionmaker[AsyncSession]
DeliveryResult = tuple[bool, int | None, str | None, str | None]


@pytest.fixture
async def session_factory(
    async_engine_fixture: Any, setup_test_db: Any
) -> SessionFactory:
    """NullPool session factory with per-test table truncation.

    Depends on ``setup_test_db`` so the session starts from a freshly
    recreated schema (stale schemas from previous runs lack new columns).
    """
    factory = async_sessionmaker(
        async_engine_fixture, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        await session.execute(text(f'TRUNCATE {TABLES} RESTART IDENTITY CASCADE'))
        await session.commit()
    return factory


@pytest.fixture
async def webhook(session_factory: SessionFactory) -> WebhookEndpoint:
    async with session_factory() as session:
        org = Organization(name=f'org-{uuid.uuid4().hex[:8]}', enabled_modules=[])
        session.add(org)
        await session.flush()
        wh = WebhookEndpoint(
            organization_id=org.id,
            name='Test WH',
            url='https://example.com/hook',
            event_types=['item.created'],
            max_retries=3,
            retry_backoff_seconds=10,
            timeout_seconds=10,
            is_active=True,
        )
        session.add(wh)
        await session.commit()
        return wh


async def _add_log(
    session_factory: SessionFactory, webhook: WebhookEndpoint, **overrides: Any
) -> uuid.UUID:
    defaults: dict[str, Any] = {
        'webhook_endpoint_id': webhook.id,
        'organization_id': webhook.organization_id,
        'event_type': 'item.created',
        'payload_json': {'foo': 'bar'},
        'attempt_number': 1,
        'next_retry_at': datetime.now(UTC) - timedelta(seconds=1),
        'delivery_status': _DELIVERY_STATUS_PENDING_RETRY,
    }
    defaults.update(overrides)
    async with session_factory() as session:
        log = WebhookDeliveryLog(**defaults)
        session.add(log)
        await session.commit()
        return cast(uuid.UUID, log.id)


async def _fetch_log(
    session_factory: SessionFactory, log_id: uuid.UUID
) -> WebhookDeliveryLog:
    async with session_factory() as session:
        log = await session.get(WebhookDeliveryLog, log_id)
        assert log is not None
        await session.refresh(log)
        session.expunge(log)
        return log


def _success_result() -> DeliveryResult:
    return (True, 200, 'ok', None)


def _failure_result() -> DeliveryResult:
    return (False, 500, 'err', 'server error')


@pytest.mark.integration
class TestRetrySemantics:
    async def test_pending_retry_delivered_successfully(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        log_id = await _add_log(session_factory, webhook)
        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            return_value=_success_result(),
        ):
            async with session_factory() as session:
                await retry_failed_deliveries(session)

        log = await _fetch_log(session_factory, log_id)
        assert log.delivery_status == _DELIVERY_STATUS_SUCCESS
        assert log.attempt_number == 2
        assert log.next_retry_at is None
        assert log.status_code == 200

    async def test_a_retry_success_ages_the_trigger_marker(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        """The endpoint answered on the second attempt, so the endpoint's
        last-triggered marker must read the retry — a success that arrived
        only after a failure used to leave the marker standing at the first
        delivery, because the retry recorded its outcome inline instead of
        through the recorder the first delivery uses."""
        stale = datetime.now(UTC) - timedelta(hours=3)
        async with session_factory() as session:
            marker = await session.get(WebhookEndpoint, webhook.id)
            assert marker is not None
            marker.last_triggered_at = stale
            await session.commit()

        await _add_log(session_factory, webhook)
        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            return_value=_success_result(),
        ):
            async with session_factory() as session:
                await retry_failed_deliveries(session)

        async with session_factory() as session:
            refreshed = await session.get(WebhookEndpoint, webhook.id)
        assert refreshed is not None
        assert refreshed.last_triggered_at is not None
        assert refreshed.last_triggered_at > stale, (
            'a delivery that only succeeded on the retry must move the '
            'last-triggered marker past the first attempt'
        )

    async def test_a_retry_failure_ages_the_marker_too(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        stale = datetime.now(UTC) - timedelta(hours=3)
        async with session_factory() as session:
            marker = await session.get(WebhookEndpoint, webhook.id)
            assert marker is not None
            marker.last_triggered_at = stale
            await session.commit()

        await _add_log(session_factory, webhook)
        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            return_value=_failure_result(),
        ):
            async with session_factory() as session:
                await retry_failed_deliveries(session)

        async with session_factory() as session:
            refreshed = await session.get(WebhookEndpoint, webhook.id)
        assert refreshed is not None
        assert refreshed.last_triggered_at is not None
        assert refreshed.last_triggered_at > stale

    async def test_failed_attempt_reschedules_with_backoff(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        log_id = await _add_log(session_factory, webhook)
        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            return_value=_failure_result(),
        ):
            async with session_factory() as session:
                await retry_failed_deliveries(session)

        log = await _fetch_log(session_factory, log_id)
        assert log.delivery_status == _DELIVERY_STATUS_PENDING_RETRY
        assert log.attempt_number == 2
        assert log.next_retry_at is not None
        assert log.next_retry_at > datetime.now(UTC)

    async def test_attempt_beyond_max_retries_marks_failed(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        log_id = await _add_log(session_factory, webhook, attempt_number=3)
        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            return_value=_failure_result(),
        ):
            async with session_factory() as session:
                await retry_failed_deliveries(session)

        log = await _fetch_log(session_factory, log_id)
        assert log.delivery_status == _DELIVERY_STATUS_FAILED

    async def test_disabled_webhook_marks_failed(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        """A manually disabled endpoint abandons the delivery, and the row
        says so as OUR stop: no status code (nobody answered this attempt),
        no borrowed text, and a reason that names the cause."""
        async with session_factory() as session:
            wh = await session.get(WebhookEndpoint, webhook.id)
            assert wh is not None
            wh.is_active = False
            await session.commit()
        # The first attempt's 500 is the receiver's answer to THAT attempt;
        # the abandonment must not carry it forward as its own.
        log_id = await _add_log(
            session_factory, webhook, status_code=500, error_message='nope'
        )

        called = False

        async def _no_call(*args: Any, **kwargs: Any) -> DeliveryResult:
            nonlocal called
            called = True
            return _success_result()

        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            side_effect=_no_call,
        ):
            async with session_factory() as session:
                await retry_failed_deliveries(session)

        assert called is False
        log = await _fetch_log(session_factory, log_id)
        assert log.delivery_status == _DELIVERY_STATUS_FAILED
        assert log.status_code is None, 'an abandonment carries no receiver status code'
        assert log.error_message is None
        assert log.abandon_reason == _ABANDON_WEBHOOK_DISABLED
        assert log.last_attempt_at is not None
        # The claim found the row through next_retry_at; a delivery we
        # stopped promising to retry must not keep telling API readers one
        # is scheduled (our own view hides it behind the status, the raw
        # delivery API does not).
        assert log.next_retry_at is None, 'an abandonment promises no next attempt'

    async def test_circuit_breaker_cut_names_itself(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        """An endpoint the breaker switched off is not 'disabled or deleted' —
        the reader must see the breaker, not go looking for the fault on the
        receiver's side."""
        async with session_factory() as session:
            wh = await session.get(WebhookEndpoint, webhook.id)
            assert wh is not None
            wh.is_active = False
            wh.auto_disabled_at = datetime.now(UTC)
            await session.commit()
        log_id = await _add_log(
            session_factory, webhook, status_code=500, error_message='nope'
        )

        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            side_effect=AssertionError('no probe leaves the process'),
        ):
            async with session_factory() as session:
                await retry_failed_deliveries(session)

        log = await _fetch_log(session_factory, log_id)
        assert log.delivery_status == _DELIVERY_STATUS_FAILED
        assert log.abandon_reason == _ABANDON_CIRCUIT_BREAKER
        assert log.status_code is None

    async def test_module_switch_off_abandons_with_its_own_reason(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        """An empty enabled_modules falls back to the registry defaults, so
        switching the module off means a list that names other modules and
        not this one."""
        async with session_factory() as session:
            org = await session.get(Organization, webhook.organization_id)
            assert org is not None
            org.enabled_modules = ['items']
            await session.commit()
        log_id = await _add_log(
            session_factory, webhook, status_code=500, error_message='nope'
        )

        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            side_effect=AssertionError('no probe leaves the process'),
        ):
            async with session_factory() as session:
                await retry_failed_deliveries(session)

        log = await _fetch_log(session_factory, log_id)
        assert log.delivery_status == _DELIVERY_STATUS_FAILED
        assert log.abandon_reason == _ABANDON_MODULE_DISABLED
        assert log.status_code is None


@pytest.mark.integration
class TestClaimThenDeliver:
    async def test_row_lock_not_held_during_http(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        """A concurrent session must be able to UPDATE the claimed row while
        the HTTP delivery is still in flight. With the old FOR UPDATE-across-
        HTTP implementation this would block until the delivery finished."""
        log_id = await _add_log(session_factory, webhook)
        concurrent_update_done = asyncio.Event()

        async def slow_delivery(*args: Any, **kwargs: Any) -> DeliveryResult:
            async with session_factory() as other:
                await other.execute(
                    text(
                        'UPDATE webhook_delivery_logs '
                        "SET error_message = 'concurrent' WHERE id = :id"
                    ),
                    {'id': log_id},
                )
                await asyncio.wait_for(other.commit(), timeout=5)
            concurrent_update_done.set()
            return _success_result()

        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            side_effect=slow_delivery,
        ):
            async with session_factory() as session:
                await asyncio.wait_for(retry_failed_deliveries(session), timeout=10)

        assert concurrent_update_done.is_set()
        log = await _fetch_log(session_factory, log_id)
        assert log.delivery_status == _DELIVERY_STATUS_SUCCESS

    async def test_stale_retrying_row_is_reclaimed(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        """Zombie claim (worker crashed mid-delivery): RETRYING with an old
        claimed_at must be claimed again and delivered."""
        log_id = await _add_log(
            session_factory,
            webhook,
            delivery_status='retrying',
            claimed_at=datetime.now(UTC) - timedelta(minutes=30),
        )
        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            return_value=_success_result(),
        ) as mock_attempt:
            async with session_factory() as session:
                await retry_failed_deliveries(session)

        mock_attempt.assert_called_once()
        log = await _fetch_log(session_factory, log_id)
        assert log.delivery_status == _DELIVERY_STATUS_SUCCESS

    async def test_fresh_retrying_row_is_left_alone(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        """A row claimed moments ago by another live worker must NOT be
        reclaimed (no double delivery)."""
        log_id = await _add_log(
            session_factory,
            webhook,
            delivery_status='retrying',
            claimed_at=datetime.now(UTC),
        )
        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            return_value=_success_result(),
        ) as mock_attempt:
            async with session_factory() as session:
                await retry_failed_deliveries(session)

        mock_attempt.assert_not_called()
        log = await _fetch_log(session_factory, log_id)
        assert log.delivery_status == 'retrying'

    async def test_future_retry_not_claimed_yet(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        log_id = await _add_log(
            session_factory,
            webhook,
            next_retry_at=datetime.now(UTC) + timedelta(hours=1),
        )
        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            return_value=_success_result(),
        ) as mock_attempt:
            async with session_factory() as session:
                await retry_failed_deliveries(session)

        mock_attempt.assert_not_called()
        log = await _fetch_log(session_factory, log_id)
        assert log.delivery_status == _DELIVERY_STATUS_PENDING_RETRY

    async def test_zombie_threshold_is_double_endpoint_timeout(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        """Spec: reclaim when claimed_at < now - 2×timeout_seconds. Default
        timeout is 10 s, so a 30 s-old claim is already a zombie."""
        log_id = await _add_log(
            session_factory,
            webhook,
            delivery_status='retrying',
            claimed_at=datetime.now(UTC) - timedelta(seconds=30),
        )
        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            return_value=_success_result(),
        ) as mock_attempt:
            async with session_factory() as session:
                await retry_failed_deliveries(session)

        mock_attempt.assert_called_once()
        log = await _fetch_log(session_factory, log_id)
        assert log.delivery_status == _DELIVERY_STATUS_SUCCESS

    async def test_long_timeout_endpoint_claim_not_prematurely_reclaimed(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        """timeout_seconds=120 → zombie threshold 240 s; a 60 s-old claim is
        still legitimately in flight and must NOT be reclaimed."""
        async with session_factory() as session:
            wh = await session.get(WebhookEndpoint, webhook.id)
            assert wh is not None
            wh.timeout_seconds = 120
            await session.commit()
        log_id = await _add_log(
            session_factory,
            webhook,
            delivery_status='retrying',
            claimed_at=datetime.now(UTC) - timedelta(seconds=60),
        )
        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            return_value=_success_result(),
        ) as mock_attempt:
            async with session_factory() as session:
                await retry_failed_deliveries(session)

        mock_attempt.assert_not_called()
        log = await _fetch_log(session_factory, log_id)
        assert log.delivery_status == 'retrying'
