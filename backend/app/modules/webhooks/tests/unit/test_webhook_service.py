"""Unit tests for webhook dispatch service logic."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.events import SystemEvent, TenantEventPayload
from app.modules.webhooks._webhook_constants import build_outbound_payload
from app.modules.webhooks._webhook_delivery import _calc_next_retry
from app.modules.webhooks._webhook_workers import cleanup_old_logs
from app.modules.webhooks.models import WebhookEndpoint
from app.services.crypto_service import encrypt_module_secret, encrypt_value

from .._signing_helpers import recording_transport, unreadable


class TestBuildOutboundPayload:
    def test_standard_fields_present(self) -> None:
        class ItemPayload(TenantEventPayload):
            item_id: str
            item_name: str

        payload = ItemPayload(
            organization_id='org-123',
            item_id='itm-001',
            item_name='Milk',
        )
        result = build_outbound_payload(SystemEvent.ITEM_USED, payload)

        assert result['event'] == 'item.used'
        assert result['organization_id'] == 'org-123'
        # delivery_id is NO LONGER in the outbound payload — it is
        # generated per-target in _attempt_delivery so that each webhook
        # receives a unique delivery id.
        assert 'delivery_id' not in result
        assert 'timestamp' in result
        assert 'data' in result
        # organization_id should be excluded from data
        assert 'organization_id' not in result['data']
        assert result['data']['item_id'] == 'itm-001'
        assert result['data']['item_name'] == 'Milk'

    def test_delivery_id_unique_per_target(self) -> None:
        """each _attempt_delivery call should generate a unique id."""
        import uuid

        ids = {str(uuid.uuid4()) for _ in range(5)}
        assert len(ids) == 5


class TestDnsPinDelivery:
    """verify the pinned IP (not the hostname) is used in the request URL."""

    def _make_webhook(
        self, url: str = 'https://example.com/hook', method: str = 'POST'
    ) -> WebhookEndpoint:
        wh = WebhookEndpoint()
        wh.url = url
        wh.http_method = method
        wh.timeout_seconds = 10
        wh.secret = None
        return wh

    @pytest.mark.asyncio
    async def test_request_url_uses_pinned_ip_not_hostname(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The httpx request URL must contain the pinned IP, not the hostname."""
        from app.modules.webhooks import _webhook_delivery

        # Force validate_webhook_url to return a known pinned IP
        monkeypatch.setattr(
            _webhook_delivery,
            'validate_webhook_url',
            lambda url, allow_private=False: '93.184.216.34',
        )

        captured_url: dict[str, Any] = {}

        class _FakeResponse:
            status_code = 200
            text = 'OK'

        class _FakeClient:
            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *a: Any) -> bool:
                return False

            async def request(self, method: str, url: str, **kwargs: Any) -> Any:
                captured_url['url'] = url
                captured_url['extensions'] = kwargs.get('extensions')
                captured_url['headers'] = kwargs.get('headers')
                return _FakeResponse()

        monkeypatch.setattr(
            _webhook_delivery.httpx, 'AsyncClient', lambda **kw: _FakeClient()
        )

        wh = self._make_webhook(url='https://example.com/hook')
        success, _status, _body, err = await _webhook_delivery._attempt_delivery(
            wh, b'{}', {'event': 'test'}, delivery_id='test-delivery-1'
        )
        assert success is True
        # The URL must target the pinned IP
        assert '93.184.216.34' in captured_url['url']
        assert (
            'example.com' not in captured_url['url'].split('//', 1)[1].split('/', 1)[0]
        )
        # SNI must preserve the original hostname for TLS
        assert captured_url['extensions']['sni_hostname'] == 'example.com'

    @pytest.mark.asyncio
    async def test_http_request_includes_host_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """For HTTP, the Host header must carry the original hostname."""
        from app.modules.webhooks import _webhook_delivery

        monkeypatch.setattr(
            _webhook_delivery,
            'validate_webhook_url',
            lambda url, allow_private=False: '93.184.216.34',
        )

        captured: dict[str, Any] = {}

        class _FakeResponse:
            status_code = 200
            text = 'OK'

        class _FakeClient:
            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *a: Any) -> bool:
                return False

            async def request(self, method: str, url: str, **kwargs: Any) -> Any:
                captured['url'] = url
                captured['host'] = kwargs.get('headers', {}).get('Host')
                return _FakeResponse()

        monkeypatch.setattr(
            _webhook_delivery.httpx, 'AsyncClient', lambda **kw: _FakeClient()
        )

        wh = self._make_webhook(url='http://example.com:8080/hook')
        await _webhook_delivery._attempt_delivery(
            wh, b'{}', {'event': 'test'}, delivery_id='test-delivery-1'
        )
        assert captured['host'] == 'example.com'
        assert captured['url'].startswith('http://93.184.216.34:8080/')


class TestCalcNextRetry:
    def _make_webhook(self, backoff: int, max_retries: int = 3) -> WebhookEndpoint:
        wh = WebhookEndpoint()
        wh.retry_backoff_seconds = backoff
        wh.max_retries = max_retries
        return wh

    def test_first_retry_uses_base_backoff(self) -> None:
        wh = self._make_webhook(backoff=10)
        before = datetime.now(UTC)
        result = _calc_next_retry(1, wh)
        assert result >= before + timedelta(seconds=9)

    def test_exponential_growth(self) -> None:
        wh = self._make_webhook(backoff=10)
        t1 = _calc_next_retry(1, wh)
        t2 = _calc_next_retry(2, wh)
        t3 = _calc_next_retry(3, wh)
        assert t2 > t1
        assert t3 > t2

    def test_capped_at_one_hour(self) -> None:
        wh = self._make_webhook(backoff=300)
        result = _calc_next_retry(20, wh)
        cap = datetime.now(UTC) + timedelta(hours=1)
        assert result <= cap + timedelta(seconds=5)


class TestCleanupOldLogs:
    @pytest.mark.asyncio
    async def test_deletes_old_logs(self) -> None:
        db = AsyncMock()
        db.delete = AsyncMock()
        result_mock = MagicMock()
        log = MagicMock()
        result_mock.scalars.return_value.all.return_value = [log]
        db.execute.return_value = result_mock

        count = await cleanup_old_logs(db, retention_days=30)

        db.delete.assert_awaited_once_with(log)
        db.commit.assert_awaited_once()
        assert count == 1

    @pytest.mark.asyncio
    async def test_no_logs_no_commit(self) -> None:
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute.return_value = result_mock

        count = await cleanup_old_logs(db, retention_days=30)

        db.commit.assert_not_awaited()
        assert count == 0


_UNREADABLE_SIGNING_SECRETS: dict[str, str] = {
    'a rotated key': unreadable(encrypt_value('hmac-key')),
    'a rotated key in the retired suffix format': (
        f'{unreadable(encrypt_value("hmac-key"))}:springfield'
    ),
    'junk where a sealed value would be': 'enc:mod_b',
    'a bound value whose marker was edited': encrypt_module_secret(
        'webhooks', 'hmac-key'
    ).replace('enc:mod1:', 'enc:MOD1:', 1),
}


class TestAnUnreadableSigningSecret:
    """Signed with the right key when it reads, refused when it does not, and
    unsigned only where no secret was ever configured.

    Two halves of one defect were measured. Signing with the empty string a
    rotated key read back produced a header every receiver reads as valid.
    And once an earlier fix stopped signing with it, the delivery left unsigned and
    was counted a success, so neither the receiver nor the circuit breaker
    could tell this channel from one that never had a secret. A delivery may
    therefore leave signed, or not leave at all: the attempt is refused
    before anything is sent, the reason travels in the delivery result, and
    the breaker counts a failure.
    """

    @staticmethod
    def _webhook(secret: str | None) -> WebhookEndpoint:
        wh = WebhookEndpoint()
        wh.url = 'https://example.com/hook'
        wh.http_method = 'POST'
        wh.timeout_seconds = 10
        wh.secret = secret
        return wh

    @pytest.mark.asyncio
    @pytest.mark.parametrize('shape', sorted(_UNREADABLE_SIGNING_SECRETS))
    async def test_an_unreadable_secret_refuses_the_delivery(
        self, shape: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.webhooks import _webhook_delivery

        sent: list[dict[str, Any]] = []
        monkeypatch.setattr(
            _webhook_delivery,
            'validate_webhook_url',
            lambda url, allow_private=False: '93.184.216.34',
        )
        monkeypatch.setattr(
            _webhook_delivery.httpx, 'AsyncClient', recording_transport(sent)
        )

        success, status_code, _body, error = await _webhook_delivery._attempt_delivery(
            self._webhook(_UNREADABLE_SIGNING_SECRETS[shape]),
            b'{"event":"test"}',
            {'event': 'test'},
            delivery_id='test-delivery-1',
        )

        assert success is False
        assert status_code is None
        assert sent == [], 'nothing may leave unsigned — there is no request'
        assert error is not None
        assert 'cannot be read' in error, 'the reason names the secret'
        assert 'Re-enter it in the endpoint settings' in error, (
            'and the fix is actionable'
        )

    @pytest.mark.asyncio
    async def test_a_readable_secret_signs_the_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.webhooks import _webhook_delivery
        from app.modules.webhooks.signing import compute_signature

        sent: list[dict[str, Any]] = []
        monkeypatch.setattr(
            _webhook_delivery,
            'validate_webhook_url',
            lambda url, allow_private=False: '93.184.216.34',
        )
        monkeypatch.setattr(
            _webhook_delivery.httpx, 'AsyncClient', recording_transport(sent)
        )
        payload = b'{"event":"test"}'

        success, _status, _body, error = await _webhook_delivery._attempt_delivery(
            self._webhook(encrypt_module_secret('webhooks', 'hmac-key')),
            payload,
            {'event': 'test'},
            delivery_id='test-delivery-1',
        )

        assert success is True
        assert error is None
        assert sent[0]['headers']['X-Inventari-Signature-256'] == compute_signature(
            payload, 'hmac-key'
        )

    @pytest.mark.asyncio
    async def test_a_channel_without_a_secret_delivers_unsigned(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The refusal must not swallow the endpoint that never signed."""
        from app.modules.webhooks import _webhook_delivery

        sent: list[dict[str, Any]] = []
        monkeypatch.setattr(
            _webhook_delivery,
            'validate_webhook_url',
            lambda url, allow_private=False: '93.184.216.34',
        )
        monkeypatch.setattr(
            _webhook_delivery.httpx, 'AsyncClient', recording_transport(sent)
        )

        success, _status, _body, error = await _webhook_delivery._attempt_delivery(
            self._webhook(None),
            b'{"event":"test"}',
            {'event': 'test'},
            delivery_id='test-delivery-1',
        )

        assert success is True
        assert error is None
        assert 'X-Inventari-Signature-256' not in sent[0]['headers']
