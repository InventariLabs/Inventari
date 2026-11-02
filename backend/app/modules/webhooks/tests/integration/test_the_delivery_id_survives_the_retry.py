"""One delivery id per event-and-endpoint, stable across every attempt.

The delivery header rolled a fresh uuid4 inside each attempt, so a receiver
answering 500 saw N attempts under N different ``X-Inventari-Delivery``
values and GitHub-style dedup-by-delivery-id — the pattern the header's own
comment promised — treated every retry as a brand-new event. A slow receiver
that answered after the sender's timeout processed the same state change
twice under two names, and nothing tied the attempts together: the history
row carried its own third id the receiver never saw, and the ping body named
a fourth.

The id is minted once with the delivery row and travels in the header and in
the payload body on every attempt of that row, so a receiver can dedup and an
administrator can match the history against the receiver's log.
"""

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.database
import app.modules.webhooks._webhook_delivery as delivery_module
from app.config import settings as app_settings
from app.core.events import SystemEvent, TenantEventPayload
from app.models.organization import Organization
from app.modules.webhooks._webhook_workers import retry_failed_deliveries
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint
from app.modules.webhooks.webhook_service import deliver_test_ping, dispatch_event

TABLES = 'webhook_delivery_logs, webhook_endpoints, organizations'

SessionFactory = async_sessionmaker[AsyncSession]

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[6]
)


class _FailingTransport:
    """An ``httpx.AsyncClient`` stand-in that answers 500 and records.

    Whatever a delivery would put on the wire — headers and body — lands in
    *calls*, so the test reads exactly what a receiver would have seen while
    the 500 keeps the delivery inside the retry path.
    """

    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self._calls = calls

    def __call__(self, **kwargs: Any) -> Any:
        transport = self

        class _FakeResponse:
            status_code = 500
            text = 'nope'

        class _FakeClient:
            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *exc: Any) -> bool:
                return False

            async def request(self, method: str, url: str, **kw: Any) -> Any:
                transport._calls.append(
                    {
                        'method': method,
                        'url': url,
                        'headers': dict(kw.get('headers') or {}),
                        'body': json.loads(bytes(kw.get('content') or b'')),
                    }
                )
                return _FakeResponse()

        return _FakeClient()


@pytest.fixture
async def sent(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(delivery_module.httpx, 'AsyncClient', _FailingTransport(calls))
    # The probe targets a loopback URL; the SSRF guard refuses that unless
    # the deployment opted in (the receiver here is a stand-in anyway).
    monkeypatch.setattr(app_settings, 'WEBHOOKS_ALLOW_PRIVATE_NETWORKS', True)
    return calls


@pytest.fixture
async def session_factory(
    async_engine_fixture: Any,
    setup_test_db: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> SessionFactory:
    factory = async_sessionmaker(
        async_engine_fixture, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        await session.execute(text(f'TRUNCATE {TABLES} RESTART IDENTITY CASCADE'))
        await session.commit()
    # The subscriber opens its own sessions through the module DB facade,
    # which forwards live to app.database.AsyncSessionLocal — point that at
    # the test engine.
    monkeypatch.setattr(app.database, 'AsyncSessionLocal', factory)
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
            url='http://127.0.0.1:9/hook',
            event_types=['item.created'],
            max_retries=3,
            retry_backoff_seconds=10,
            timeout_seconds=10,
            is_active=True,
        )
        session.add(wh)
        await session.commit()
        return wh


async def _dispatch_item_created(webhook: WebhookEndpoint) -> None:
    await dispatch_event(
        SystemEvent.ITEM_CREATED,
        TenantEventPayload(organization_id=str(webhook.organization_id), detail='x'),
    )


async def _force_due(session_factory: SessionFactory, webhook: WebhookEndpoint) -> None:
    async with session_factory() as session:
        log = await session.scalar(
            select(WebhookDeliveryLog).where(
                WebhookDeliveryLog.webhook_endpoint_id == webhook.id
            )
        )
        assert log is not None
        log.delivery_status = 'pending_retry'
        log.next_retry_at = datetime.now(UTC)
        session.add(log)
        await session.commit()


def _header_of(call: dict[str, Any]) -> str:
    return str(call['headers']['X-Inventari-Delivery'])


async def test_retries_arrive_under_one_delivery_header(
    session_factory: SessionFactory,
    webhook: WebhookEndpoint,
    sent: list[dict[str, Any]],
) -> None:
    await _dispatch_item_created(webhook)
    await _force_due(session_factory, webhook)
    async with session_factory() as session:
        await retry_failed_deliveries(session)

    assert len(sent) == 2, 'the 500 answer must produce exactly one retry'
    assert _header_of(sent[0]) == _header_of(sent[1]), (
        'both attempts carry the same X-Inventari-Delivery'
    )


async def test_payload_body_and_row_agree_on_the_delivery_id(
    session_factory: SessionFactory,
    webhook: WebhookEndpoint,
    sent: list[dict[str, Any]],
) -> None:
    await _dispatch_item_created(webhook)
    await _force_due(session_factory, webhook)
    async with session_factory() as session:
        await retry_failed_deliveries(session)

    async with session_factory() as session:
        log = await session.scalar(
            select(WebhookDeliveryLog).where(
                WebhookDeliveryLog.webhook_endpoint_id == webhook.id
            )
        )
        assert log is not None

    for index, call in enumerate(sent):
        body = call['body']
        assert body.get('delivery_id') == _header_of(call), (
            f'attempt {index + 1}: the payload body carries the header id'
        )
        assert log.delivery_id == _header_of(call), (
            f'attempt {index + 1}: the delivery row stores the id the receiver saw'
        )


async def test_ping_header_and_body_carry_one_delivery_id(
    session_factory: SessionFactory,
    webhook: WebhookEndpoint,
    sent: list[dict[str, Any]],
) -> None:
    async with session_factory() as session:
        await deliver_test_ping(session, webhook, str(webhook.organization_id))

    assert sent, 'the ping must reach the captured client'
    assert sent[0]['body'].get('delivery_id') == _header_of(sent[0]), (
        'the ping body id is the header id, not a second roll'
    )


async def test_ping_speaks_the_envelope_a_real_event_speaks(
    session_factory: SessionFactory,
    webhook: WebhookEndpoint,
    sent: list[dict[str, Any]],
) -> None:
    async with session_factory() as session:
        await deliver_test_ping(session, webhook, str(webhook.organization_id))

    body = sent[0]['body']
    assert set(body) == {
        'schema_version',
        'event',
        'timestamp',
        'delivery_id',
        'organization_id',
        'data',
    }, 'a receiver validated against the ping must accept the first real event'
    assert body['schema_version'] == 1
    assert body['event'] == 'webhook.test'
    assert body['organization_id'] == str(webhook.organization_id)
    assert body['data']['webhook_id'] == str(webhook.id)
    assert 'organization_id' not in body['data'], 'data never repeats the envelope key'


def test_the_documented_payload_format_is_the_one_that_ships() -> None:
    doc_path = _REPO_ROOT / 'docs' / 'subsystems' / 'WEBHOOKS.md'
    assert doc_path.is_file(), (
        f'{doc_path} is not reachable: point INVENTARI_REPO_ROOT at the checkout'
    )
    doc = doc_path.read_text(encoding='utf-8')
    assert '"delivery_id"' in doc, 'the payload example shows the delivery id'
    assert 'data.item_id' not in doc, (
        'the example must not promise an item_id key the payload never carries'
    )
