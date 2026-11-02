"""Unit tests for the router-aware rate-limit middleware.

slowapi's stock middleware resolves the request handler by walking
``app.routes`` and reading ``route.endpoint``. FastAPI keeps every
``include_router()`` call as a single ``_IncludedRouter`` node that has no
``endpoint``, so the stock lookup returns ``None`` for the whole API and slowapi
treats those requests as exempt — the default limits then apply to nothing.
These tests pin the replacement lookup and the enforcement it restores.
"""

import asyncio
import time
from collections import OrderedDict
from types import SimpleNamespace

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import app.core.limiter as limiter_module
from app.core.limiter import rate_limit_exceeded_handler
from app.core.limiter_middleware import (
    RouterAwareSlowAPIMiddleware,
    find_route_handler,
)


def _scope(path: str, method: str = 'GET') -> dict:
    return {
        'type': 'http',
        'method': method,
        'path': path,
        'root_path': '',
        'headers': [],
        'query_string': b'',
    }


@pytest.fixture
def limited_app() -> FastAPI:
    """App whose endpoints live behind ``include_router``, limited to 3/minute."""
    limiter = Limiter(
        key_func=lambda request: 'test-bucket',
        storage_uri='memory://',
        default_limits=['3/minute'],
    )

    nested = APIRouter()

    @nested.get('/items')
    async def list_items():
        return {'items': []}

    @nested.get('/exempt')
    @limiter.exempt
    async def exempt_endpoint():
        return {'ok': True}

    outer = APIRouter(prefix='/v1')
    outer.include_router(nested)

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(RouterAwareSlowAPIMiddleware)
    app.include_router(outer, prefix='/api')

    @app.get('/health')
    async def health():
        return {'status': 'healthy'}

    return app


class TestFindRouteHandler:
    def test_resolves_handler_behind_include_router(self, limited_app):
        handler = find_route_handler(limited_app.routes, _scope('/api/v1/items'))
        assert handler is not None
        assert handler.__name__ == 'list_items'

    def test_resolves_top_level_handler(self, limited_app):
        handler = find_route_handler(limited_app.routes, _scope('/health'))
        assert handler is not None
        assert handler.__name__ == 'health'

    def test_returns_none_for_unknown_path(self, limited_app):
        assert find_route_handler(limited_app.routes, _scope('/nope')) is None

    def test_returns_none_when_method_does_not_match(self, limited_app):
        assert (
            find_route_handler(limited_app.routes, _scope('/api/v1/items', 'DELETE'))
            is None
        )


class TestDefaultLimitEnforcement:
    def test_undecorated_nested_endpoint_hits_default_limit(self, limited_app):
        with TestClient(limited_app) as client:
            for _ in range(3):
                assert client.get('/api/v1/items').status_code == 200
            assert client.get('/api/v1/items').status_code == 429

    def test_exempt_endpoint_is_not_limited(self, limited_app):
        with TestClient(limited_app) as client:
            for _ in range(5):
                assert client.get('/api/v1/exempt').status_code == 200

    def test_default_limits_resolve_without_a_request_object(self, limited_app):
        """A limit provider taking ``key`` needs a request slowapi never passes
        to default limits — every request would then raise 500.
        """
        for limit_group in limited_app.state.limiter._default_limits:
            assert list(limit_group)


class TestTheRefusalEnvelope:
    def test_a_refused_request_answers_in_the_coded_envelope(self, limited_app):
        """429 used to be the one error under ``{"error": ...}``.

        The handler is synchronous on purpose: ``sync_check_limits`` in the
        middleware falls back to slowapi's own handler for a coroutine, so an
        ``async def`` here would leave the default limits answering the old
        shape while only the decorator paths used the new one.
        """
        limited_app.add_exception_handler(
            RateLimitExceeded, rate_limit_exceeded_handler
        )

        with TestClient(limited_app) as client:
            for _ in range(3):
                assert client.get('/api/v1/items').status_code == 200
            response = client.get('/api/v1/items')

        assert response.status_code == 429
        body = response.json()
        assert set(body) == {'detail'}
        assert body['detail']['code'] == 'RATE_LIMIT_EXCEEDED'
        assert body['detail']['message']
        assert body['detail']['limit']


@pytest.fixture
def lookups(limited_app, monkeypatch) -> list[str]:
    """Record every credential the middleware looks up; none is issued."""
    import app.core.limiter_middleware as middleware
    import app.database as database

    class _Session:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    seen: list[str] = []

    async def _list_nothing(db):
        return middleware._nothing_issued

    async def _refuse(db, raw_key):
        seen.append(raw_key)
        limiter_module.record_api_key_verdict(raw_key, issued=False)
        return None

    monkeypatch.setattr(database, 'AsyncSessionLocal', _Session)
    monkeypatch.setattr(middleware, 'resolve_api_key', _refuse)
    monkeypatch.setattr(middleware, 'load_issued_api_keys', _list_nothing)
    monkeypatch.setattr(limiter_module, '_forged_lookups', OrderedDict())
    monkeypatch.setattr(limiter_module, '_issued_api_key_buckets', OrderedDict())
    monkeypatch.setattr(middleware, '_issued_list', middleware._nothing_issued)
    monkeypatch.setattr(middleware, '_issued_list_loaded_at', float('-inf'))
    monkeypatch.setattr(middleware, '_issued_list_load', None)
    monkeypatch.setattr(middleware, '_listed_lookups', {})
    # A forged key past the budget waits for a list loaded after it arrived.
    monkeypatch.setattr(middleware, '_ISSUED_LIST_REFRESH_SECONDS', 0.01)
    limited_app.state.limiter._key_func = lambda request: 'test-bucket'
    return seen


class TestForgedKeyLookupsAreBounded:
    """A key-shaped credential is checked against the database before the
    limits are counted. A sender who keeps presenting values nobody issued must
    not turn that check into unbounded database work, whatever its allowance.
    """

    def test_rotating_forged_keys_stop_reaching_the_database(
        self, limited_app, lookups
    ):
        budget = limiter_module._FORGED_LOOKUPS_PER_WINDOW
        with TestClient(limited_app) as client:
            for i in range(budget * 3):
                client.get(
                    '/api/v1/items', headers={'X-API-Key': f'inv_live_forged{i}'}
                )
        assert len(lookups) == budget

    def test_the_same_forged_key_repeated_is_bounded_too(self, limited_app, lookups):
        budget = limiter_module._FORGED_LOOKUPS_PER_WINDOW
        with TestClient(limited_app) as client:
            for _ in range(budget * 3):
                client.get('/api/v1/items', headers={'X-API-Key': 'inv_live_forged'})
        assert len(lookups) == budget

    def test_another_sender_keeps_its_own_budget(self, limited_app, lookups):
        budget = limiter_module._FORGED_LOOKUPS_PER_WINDOW
        with TestClient(limited_app, client=('198.51.100.1', 5000)) as spent:
            for i in range(budget + 5):
                spent.get('/api/v1/items', headers={'X-API-Key': f'inv_live_forged{i}'})
        assert len(lookups) == budget
        with TestClient(limited_app, client=('198.51.100.2', 5000)) as fresh:
            fresh.get('/api/v1/items', headers={'X-API-Key': 'inv_live_other'})
        assert lookups[-1] == 'inv_live_other'

    def test_an_accepted_key_does_not_spend_the_budget(
        self, limited_app, monkeypatch, lookups
    ):
        import app.core.limiter_middleware as middleware

        async def _accept(db, raw_key):
            lookups.append(raw_key)
            return object()

        monkeypatch.setattr(middleware, 'resolve_api_key', _accept)
        budget = limiter_module._FORGED_LOOKUPS_PER_WINDOW
        with TestClient(limited_app) as client:
            for i in range(budget * 2):
                client.get('/api/v1/items', headers={'X-API-Key': f'inv_live_ok{i}'})
        assert len(lookups) == budget * 2

    async def test_concurrent_forged_keys_do_not_outrun_the_budget(
        self, limited_app, lookups, monkeypatch
    ):
        """Requests that are all in flight before any refusal comes back are
        still bounded: the budget is spent when a lookup starts, not when it
        ends."""
        import app.core.limiter_middleware as middleware

        async def _slow_refuse(db, raw_key):
            lookups.append(raw_key)
            await asyncio.sleep(0.01)
            return None

        monkeypatch.setattr(middleware, 'resolve_api_key', _slow_refuse)
        budget = limiter_module._FORGED_LOOKUPS_PER_WINDOW
        transport = httpx.ASGITransport(app=limited_app)
        async with httpx.AsyncClient(
            transport=transport, base_url='http://testserver'
        ) as client:
            await asyncio.gather(
                *(
                    client.get(
                        '/api/v1/items', headers={'X-API-Key': f'inv_live_forged{i}'}
                    )
                    for i in range(budget * 4)
                )
            )
        assert len(lookups) == budget


class TestIssuedKeysBehindASpentSender:
    """A sender out of lookups can share its address with an issued key — an
    office behind one NAT with a forger in it. That key must still be looked
    up, or it counts under the address and is refused before authentication
    can accept it; the forged keys around it must still cost no lookup.
    """

    INTERVAL = 0.05

    @pytest.fixture
    def issued_list(self, monkeypatch, lookups) -> SimpleNamespace:
        """An issued-key list naming ``issued`` (accepted on lookup) and
        ``expired`` (refused on lookup); ``loads`` records every load, and a
        load waits for ``gate`` while it is cleared."""
        import app.core.limiter_middleware as middleware

        state = SimpleNamespace(
            issued={'inv_live_issued'},
            expired={'inv_live_expired'},
            loads=[],
            gate=asyncio.Event(),
        )
        state.gate.set()

        async def _load(db):
            names = frozenset(state.issued | state.expired)
            state.loads.append(names)
            await state.gate.wait()
            return lambda raw_key: raw_key in names

        async def _resolve(db, raw_key):
            lookups.append(raw_key)
            await asyncio.sleep(0.01)
            issued = raw_key in state.issued
            limiter_module.record_api_key_verdict(raw_key, issued=issued)
            return object() if issued else None

        monkeypatch.setattr(middleware, 'load_issued_api_keys', _load)
        monkeypatch.setattr(middleware, 'resolve_api_key', _resolve)
        monkeypatch.setattr(middleware, '_ISSUED_LIST_REFRESH_SECONDS', self.INTERVAL)
        return state

    @staticmethod
    def _client(app) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver'
        )

    @staticmethod
    async def _spend_the_budget(client) -> None:
        for i in range(limiter_module._FORGED_LOOKUPS_PER_WINDOW):
            await client.get(
                '/api/v1/items', headers={'X-API-Key': f'inv_live_forged{i}'}
            )

    async def test_an_issued_key_is_still_looked_up(
        self, limited_app, lookups, issued_list
    ):
        async with self._client(limited_app) as client:
            await self._spend_the_budget(client)
            await client.get('/api/v1/items', headers={'X-API-Key': 'inv_live_issued'})
        assert lookups[-1] == 'inv_live_issued'

    async def test_forged_keys_past_the_budget_cost_no_lookup(
        self, limited_app, lookups, issued_list
    ):
        budget = limiter_module._FORGED_LOOKUPS_PER_WINDOW
        async with self._client(limited_app) as client:
            await self._spend_the_budget(client)
            await asyncio.gather(
                *(
                    client.get(
                        '/api/v1/items', headers={'X-API-Key': f'inv_live_more{i}'}
                    )
                    for i in range(budget * 3)
                )
            )
        assert len(lookups) == budget
        assert len(issued_list.loads) <= 2

    async def test_list_loads_are_paced_however_many_forged_keys_wait(
        self, limited_app, lookups, issued_list
    ):
        async with self._client(limited_app) as client:
            await self._spend_the_budget(client)
            started = time.monotonic()
            for i in range(10):
                await client.get(
                    '/api/v1/items', headers={'X-API-Key': f'inv_live_more{i}'}
                )
            elapsed = time.monotonic() - started
        assert len(issued_list.loads) <= elapsed / self.INTERVAL + 1

    async def test_an_issued_key_arriving_during_a_load_is_looked_up(
        self, limited_app, lookups, issued_list
    ):
        """A load already in flight may have started before the key's request
        arrived; the key waits for one that did not, instead of being judged
        by the list as it stood."""
        async with self._client(limited_app) as client:
            await self._spend_the_budget(client)
            issued_list.gate.clear()
            forged = asyncio.ensure_future(
                client.get('/api/v1/items', headers={'X-API-Key': 'inv_live_more'})
            )
            await asyncio.sleep(0.01)
            assert len(issued_list.loads) == 1
            issued = asyncio.ensure_future(
                client.get('/api/v1/items', headers={'X-API-Key': 'inv_live_issued'})
            )
            await asyncio.sleep(0.01)
            issued_list.gate.set()
            await asyncio.gather(forged, issued)
        assert lookups[-1] == 'inv_live_issued'

    async def test_a_key_issued_after_the_last_load_is_looked_up(
        self, limited_app, lookups, issued_list
    ):
        async with self._client(limited_app) as client:
            await self._spend_the_budget(client)
            await client.get('/api/v1/items', headers={'X-API-Key': 'inv_live_more'})
            assert 'inv_live_new' not in issued_list.loads[-1]
            issued_list.issued.add('inv_live_new')
            await client.get('/api/v1/items', headers={'X-API-Key': 'inv_live_new'})
        assert lookups[-1] == 'inv_live_new'

    async def test_requests_presenting_one_listed_key_share_its_lookup(
        self, limited_app, lookups, issued_list
    ):
        async with self._client(limited_app) as client:
            await self._spend_the_budget(client)
            await asyncio.gather(
                *(
                    client.get(
                        '/api/v1/items', headers={'X-API-Key': 'inv_live_issued'}
                    )
                    for _ in range(10)
                )
            )
        assert lookups.count('inv_live_issued') == 1

    async def test_a_listed_key_once_refused_is_not_looked_up_again(
        self, limited_app, lookups, issued_list
    ):
        """An expired key is still on the list until the next load; refusing it
        once is the answer every request with it gets until then, so repeating
        it is no more work than a forged key."""
        async with self._client(limited_app) as client:
            await self._spend_the_budget(client)
            started = time.monotonic()
            for _ in range(10):
                await client.get(
                    '/api/v1/items', headers={'X-API-Key': 'inv_live_expired'}
                )
            elapsed = time.monotonic() - started
        assert lookups.count('inv_live_expired') <= elapsed / self.INTERVAL + 1

    async def test_a_refused_listed_key_is_asked_about_again_on_the_next_list(
        self, limited_app, lookups, issued_list
    ):
        """A refusal answers only the requests that were waiting on it: a key
        refused while its module was switched off and presented again at once
        after the module is back waits for a list loaded since, and is looked
        up again instead of being refused for what that list still says."""
        async with self._client(limited_app) as client:
            await self._spend_the_budget(client)
            await client.get('/api/v1/items', headers={'X-API-Key': 'inv_live_expired'})
            issued_list.expired.discard('inv_live_expired')
            issued_list.issued.add('inv_live_expired')
            await client.get('/api/v1/items', headers={'X-API-Key': 'inv_live_expired'})
        assert lookups.count('inv_live_expired') == 2
