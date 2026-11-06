"""Unit tests for the rate limiter client-key resolution.

The limiter buckets issued API keys and signed JWT users separately and uses
the client IP for anonymous or unverified API-key traffic. Bucketing the whole
instance under one proxy IP (A4) is avoided by ``--forwarded-allow-ips`` on
gunicorn, which makes ``request.client.host`` the real client IP; these tests
cover the key function itself.

An API key earns a bucket of its own only once authentication has accepted
it: the key function runs before any route, so a header it took on trust
would let a client rotate made-up keys and meet a fresh count on each one.
"""

import hashlib
import time
import uuid
from typing import cast

import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

import app.core.api_key_auth as api_key_auth
import app.core.limiter as limiter_module
from app.config import settings
from app.core.api_key_auth import ApiKeyIdentity, resolve_api_key
from app.core.limiter import get_client_key, unverified_api_key


def _request(
    headers: dict[str, str] | None = None, client: str = '203.0.113.7'
) -> Request:
    scope = {
        'type': 'http',
        'method': 'GET',
        'path': '/',
        'headers': [
            (k.lower().encode('latin-1'), v.encode('latin-1'))
            for k, v in (headers or {}).items()
        ],
        'client': (client, 12345),
        'query_string': b'',
    }
    return Request(scope)


def _jwt_for(user_id: str) -> str:
    return jwt.encode(
        {'sub': user_id, 'type': 'access'},
        settings.SECRET_KEY or 'test-secret',
        algorithm=settings.ALGORITHM,
    )


# The stub resolver below never touches the session.
_NO_DB = cast(AsyncSession, None)


def _raw_key() -> str:
    # A key of its own per test: what authentication accepted is remembered
    # for the process, and a shared literal would carry it between tests.
    return 'inv_live_' + uuid.uuid4().hex


@pytest.fixture
def issued_keys(monkeypatch) -> set[str]:
    """Keys the stub resolver accepts, as the api_keys module would."""
    issued: set[str] = set()

    async def resolver(db, raw_key):
        if raw_key not in issued:
            return None
        return ApiKeyIdentity(user_id=uuid.uuid4(), key_prefix=raw_key[:15])

    monkeypatch.setattr(api_key_auth, '_resolver', resolver)
    return issued


async def _issue(issued_keys: set[str]) -> str:
    raw = _raw_key()
    issued_keys.add(raw)
    assert await resolve_api_key(_NO_DB, raw) is not None
    return raw


class TestGetClientKey:
    def test_unverified_key_headers_cannot_choose_a_bucket(self):
        for headers in (
            {'X-API-Key': 'arbitrary-one'},
            {'X-API-Key': 'arbitrary-two'},
            {'Authorization': 'Bearer inv_live_random-one'},
            {'Authorization': 'Bearer inv_live_random-two'},
        ):
            assert get_client_key(_request(headers=headers)) == 'ip:203.0.113.7'

    def test_anonymous_falls_back_to_ip(self):
        request = _request()
        assert get_client_key(request) == 'ip:203.0.113.7'

    def test_different_ips_get_different_keys(self):
        key_a = get_client_key(_request(client='198.51.100.1'))
        key_b = get_client_key(_request(client='198.51.100.2'))
        assert key_a != key_b

    async def test_api_key_buckets_per_key_hash(self, issued_keys):
        raw = await _issue(issued_keys)
        request = _request(headers={'Authorization': f'Bearer {raw}'})
        key = get_client_key(request)
        expected = hashlib.sha256(raw.encode()).hexdigest()[:16]
        assert key == f'apikey:{expected}'
        # Raw key material must not end up in the bucket key.
        assert raw not in key

    async def test_a_key_in_its_own_header_shares_the_bearer_forms_bucket(
        self, issued_keys
    ):
        raw = await _issue(issued_keys)
        own = get_client_key(_request(headers={'X-API-Key': raw}))
        bearer = get_client_key(_request(headers={'Authorization': f'Bearer {raw}'}))
        assert own == bearer
        assert own.startswith('apikey:')
        assert raw not in own

    async def test_distinct_api_keys_get_distinct_buckets(self, issued_keys):
        key_a = get_client_key(
            _request(headers={'Authorization': f'Bearer {await _issue(issued_keys)}'})
        )
        key_b = get_client_key(
            _request(headers={'Authorization': f'Bearer {await _issue(issued_keys)}'})
        )
        assert key_a != key_b

    def test_an_unissued_key_header_counts_as_the_client_ip(self, issued_keys):
        """A made-up key is the client it came from, not a new client."""
        for _ in range(3):
            request = _request(headers={'X-API-Key': f'does-not-exist-{uuid.uuid4()}'})
            assert get_client_key(request) == 'ip:203.0.113.7'

    def test_an_unissued_key_shaped_bearer_counts_as_the_client_ip(self, issued_keys):
        request = _request(headers={'Authorization': f'Bearer {_raw_key()}'})
        assert get_client_key(request) == 'ip:203.0.113.7'

    async def test_a_refused_key_falls_back_to_the_signed_in_user(self, issued_keys):
        token = _jwt_for('44444444-4444-4444-4444-444444444444')
        request = _request(
            headers={'X-API-Key': _raw_key(), 'Authorization': f'Bearer {token}'}
        )
        assert get_client_key(request) == 'user:44444444-4444-4444-4444-444444444444'

    async def test_a_key_authentication_refuses_loses_its_bucket(self, issued_keys):
        """Revoked or expired: the next refusal forgets the key."""
        raw = await _issue(issued_keys)
        assert get_client_key(_request(headers={'X-API-Key': raw})).startswith(
            'apikey:'
        )
        issued_keys.discard(raw)
        assert await resolve_api_key(_NO_DB, raw) is None
        assert get_client_key(_request(headers={'X-API-Key': raw})) == 'ip:203.0.113.7'

    async def test_only_an_unknown_key_shaped_credential_is_sent_to_be_checked(
        self, issued_keys
    ):
        """The middleware asks about these before counting; nothing else."""
        unknown = _raw_key()
        assert unverified_api_key(_request(headers={'X-API-Key': unknown})) == unknown
        bearer = _request(headers={'Authorization': f'Bearer {unknown}'})
        assert unverified_api_key(bearer) == unknown
        # A value without the issued prefix can never be a key.
        assert unverified_api_key(_request(headers={'X-API-Key': 'made-up'})) is None
        assert unverified_api_key(_request()) is None
        raw = await _issue(issued_keys)
        assert unverified_api_key(_request(headers={'X-API-Key': raw})) is None

    async def test_an_accepted_key_is_checked_again_after_its_time_to_live(
        self, issued_keys, monkeypatch
    ):
        """A revoked key stops counting as its own client on routes that never
        authenticate it, too."""
        raw = await _issue(issued_keys)
        later = time.monotonic() + limiter_module._ISSUED_API_KEY_TTL_SECONDS + 1
        monkeypatch.setattr(limiter_module.time, 'monotonic', lambda: later)
        request = _request(headers={'X-API-Key': raw})
        assert get_client_key(request) == 'ip:203.0.113.7'
        assert unverified_api_key(request) == raw

    def test_valid_jwt_buckets_per_user(self):
        token = _jwt_for('11111111-1111-1111-1111-111111111111')
        request = _request(headers={'Authorization': f'Bearer {token}'})
        assert get_client_key(request) == 'user:11111111-1111-1111-1111-111111111111'

    def test_expired_jwt_still_identifies_user(self):
        import time

        token = jwt.encode(
            {
                'sub': '22222222-2222-2222-2222-222222222222',
                'exp': int(time.time()) - 60,
            },
            settings.SECRET_KEY or 'test-secret',
            algorithm=settings.ALGORITHM,
        )
        request = _request(headers={'Authorization': f'Bearer {token}'})
        assert get_client_key(request) == 'user:22222222-2222-2222-2222-222222222222'

    def test_invalid_signature_falls_back_to_ip(self):
        token = jwt.encode(
            {'sub': '33333333-3333-3333-3333-333333333333'},
            'wrong-secret',
            algorithm=settings.ALGORITHM,
        )
        request = _request(headers={'Authorization': f'Bearer {token}'})
        assert get_client_key(request) == 'ip:203.0.113.7'

    def test_garbage_bearer_token_falls_back_to_ip(self):
        request = _request(headers={'Authorization': 'Bearer not-a-jwt'})
        assert get_client_key(request) == 'ip:203.0.113.7'

    def test_no_client_ip_returns_loopback(self):
        request = _request()
        request.scope['client'] = None
        assert get_client_key(request) == 'ip:127.0.0.1'

    def test_forwarded_for_header_is_not_trusted_at_app_level(self):
        """X-Forwarded-For is rewritten into scope['client'] by uvicorn's
        ProxyHeadersMiddleware (enabled via gunicorn --forwarded-allow-ips);
        the app itself must NOT parse the header — an untrusted spoof would
        otherwise hop buckets. Here the scope client is still the proxy peer.
        """
        request = _request(
            headers={'X-Forwarded-For': '198.51.100.99'}, client='10.0.0.2'
        )
        assert get_client_key(request) == 'ip:10.0.0.2'
