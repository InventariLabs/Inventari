"""
Integration tests verifying that rate limits actually fire and return 429.

The standard `client` fixture disables rate limiting via the session-scoped
autouse `disable_rate_limiting` fixture in `conftest.py`. These tests
re-enable the limiter explicitly and exercise the limits configured on
authentication endpoints.

Isolation
---------
The limiter counts in the stack's Redis, which every xdist worker shares, so
a test gets a bucket nobody else can touch: ``get_client_key`` falls back to
``get_remote_address`` for an anonymous request, and the fixture points that
name, as ``app.core.limiter`` holds it, at a fresh UUID. Counters are never
wiped. A global reset used to run in each worker that started this module,
and it cleared the counters of a test halfway through its walk on another
worker — the fourth request of a 3/hour limit then passed with 202.

Two things did not isolate anything, and are worth knowing before changing
this: patching ``slowapi.util.get_remote_address`` misses the name
``app.core.limiter`` imported, and patching ``limiter._key_func`` misses every
``@limiter.limit`` route, which captured its key function when it was
decorated. Both were here, and every test counted under ``ip:testclient``.
"""

import hashlib
import uuid
from collections import OrderedDict

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.core.limiter as limiter_module
import app.core.limiter_middleware as middleware
from app.config import settings
from app.core.contracts import API_KEY_PREFIX
from app.core.limiter import limiter
from app.database import get_async_db, get_db
from app.main import app
from app.modules.api_keys.models import ApiKey


@pytest.fixture
def rate_limited_client(db_session, async_engine_fixture, monkeypatch):
    """TestClient with rate limiting enabled and a bucket of its own."""

    def override_get_db():
        try:
            db_session.commit()
        except Exception:  # noqa: BLE001 — fixture hygiene: whatever the commit hit, start clean
            db_session.rollback()
        try:
            yield db_session
        finally:
            try:
                db_session.commit()
            except Exception:  # noqa: BLE001 — fixture hygiene: whatever the commit hit, start clean
                db_session.rollback()

    async_factory = async_sessionmaker(
        async_engine_fixture, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_async_db():
        async with async_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_async_db] = override_get_async_db

    monkeypatch.setattr(limiter, 'enabled', True)
    # The login limit is configurable via RATE_LIMIT_LOGIN; pin the value this
    # file documents instead of inheriting whatever the host stack sets.
    monkeypatch.setattr(settings, 'RATE_LIMIT_LOGIN', '5 per minute')
    bucket = f'rate-limit-test-{uuid.uuid4().hex}'
    monkeypatch.setattr(limiter_module, 'get_remote_address', lambda request: bucket)

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.integration
class TestAuthRateLimitEnforced:
    """P0 #1: SlowAPIMiddleware registered + decorator limits actually fire."""

    @pytest.mark.parametrize('header', ['X-API-Key', 'Authorization'])
    def test_changing_unverified_keys_does_not_reset_login_limit(
        self, rate_limited_client, header
    ):
        for number in range(6):
            value = f'inv_live_unverified_{number}'
            if header == 'Authorization':
                value = f'Bearer {value}'
            response = rate_limited_client.post(
                '/api/v1/auth/login',
                data={'username': 'nosuch@example.com', 'password': 'wrong'},
                headers={header: value},
            )
            assert response.status_code == (401 if number < 5 else 429)

    @pytest.mark.parametrize('header', ['X-API-Key', 'Authorization'])
    def test_changing_unverified_keys_does_not_reset_password_limit(
        self, rate_limited_client, header
    ):
        for number in range(4):
            value = f'inv_live_unverified_{number}'
            if header == 'Authorization':
                value = f'Bearer {value}'
            response = rate_limited_client.post(
                '/api/v1/auth/password-reset/request',
                json={'email': 'flood@example.com'},
                headers={header: value},
            )
            assert response.status_code == (202 if number < 3 else 429)

    def test_login_429_after_five_attempts(self, rate_limited_client):
        """`POST /auth/login` is limited to 5/minute by IP — 6th call returns 429."""
        for _ in range(5):
            response = rate_limited_client.post(
                '/api/v1/auth/login',
                data={'username': 'nosuch@example.com', 'password': 'wrong'},
            )
            assert response.status_code == 401, response.text

        response = rate_limited_client.post(
            '/api/v1/auth/login',
            data={'username': 'nosuch@example.com', 'password': 'wrong'},
        )
        assert response.status_code == 429, response.text

    def test_a_burned_bucket_is_nobody_else(self, rate_limited_client, monkeypatch):
        """The isolation above is real, not decorative — and here is its tooth.

        The limiter counts in the stack's Redis, which every xdist worker
        shares. Two earlier patches looked right and changed nothing — one
        missed the name ``app.core.limiter`` imported, the other missed every
        ``@limiter.limit`` route, which captured its key function when it was
        decorated — so all of these tests counted under ``ip:testclient`` and
        this file went red at random depending on which worker got there
        first. Burning one bucket and watching the next arrive untouched is
        the assertion that fails when the per-test name stops reaching the key
        function: the walk and the check after it share a store, and a shared
        store is exactly the defect.
        """
        login = {'username': 'nosuch@example.com', 'password': 'wrong'}
        burned = [
            rate_limited_client.post('/api/v1/auth/login', data=login).status_code
            for _ in range(6)
        ]
        assert burned == [401] * 5 + [429]

        monkeypatch.setattr(
            limiter_module, 'get_remote_address', lambda request: 'rate-limit-test-next'
        )
        fresh = rate_limited_client.post('/api/v1/auth/login', data=login).status_code
        assert fresh == 401, (
            'a client of its own still gets 401 where the burned one got 429; '
            f'got {fresh} — the two are counting in one bucket'
        )

    def test_made_up_api_keys_do_not_buy_a_fresh_allowance(self, rate_limited_client):
        """A key header is a client of its own only once it authenticated.

        The key function runs before any route, and it used to take every
        nonempty ``X-API-Key`` — and every key-shaped Bearer token — as a new
        client, so a burned bucket was refilled by sending a different
        made-up key on each request.
        """
        login = {'username': 'nosuch@example.com', 'password': 'wrong'}
        burned = [
            rate_limited_client.post('/api/v1/auth/login', data=login).status_code
            for _ in range(6)
        ]
        assert burned == [401] * 5 + [429]

        forged = [
            {'X-API-Key': f'does-not-exist-{uuid.uuid4()}'},
            {'X-API-Key': f'inv_live_{uuid.uuid4().hex}'},
            {'Authorization': f'Bearer inv_live_{uuid.uuid4().hex}'},
        ]
        statuses = [
            rate_limited_client.post(
                '/api/v1/auth/login', data=login, headers=headers
            ).status_code
            for headers in forged
        ]
        assert statuses == [429] * len(forged)

    def test_issued_keys_keep_their_own_allowance_before_they_authenticate(
        self, rate_limited_client, db_session, test_user, monkeypatch
    ):
        """An issued key is a client of its own from its first request.

        The key function runs before authentication, so a key this worker had
        never seen authenticate used to count under its sender: once the
        sender's allowance was spent, an issued key arriving at a fresh worker
        was refused before it could authenticate, and two keys behind one
        address shared one count. The limiter now asks about such a key before
        counting it.
        """
        raws = []
        for _ in range(2):
            raw = f'{API_KEY_PREFIX}{uuid.uuid4().hex}'
            db_session.add(
                ApiKey(
                    organization_id=test_user.organization_id,
                    user_id=test_user.id,
                    name='CI',
                    hashed_key=hashlib.sha256(raw.encode()).hexdigest(),
                    key_prefix=raw[:20],
                )
            )
            raws.append(raw)
        db_session.commit()
        # A fresh worker: no key has authenticated in this process.
        monkeypatch.setattr(limiter_module, '_issued_api_key_buckets', OrderedDict())

        login = {'username': 'nosuch@example.com', 'password': 'wrong'}
        burned = [
            rate_limited_client.post('/api/v1/auth/login', data=login).status_code
            for _ in range(6)
        ]
        assert burned == [401] * 5 + [429]

        statuses = [
            rate_limited_client.post(
                '/api/v1/auth/login', data=login, headers={'X-API-Key': raw}
            ).status_code
            for raw in raws
            for _ in range(5)
        ]
        assert statuses == [401] * 10

    def test_an_issued_key_keeps_its_allowance_behind_a_forger(
        self, rate_limited_client, db_session, test_user, monkeypatch
    ):
        """An address out of lookups and out of allowance still lets an issued
        key through to authentication.

        A forger spends its address's lookups, after which an unknown key there
        is no longer looked up one by one. An issued key from the same address
        — an office behind one NAT — used to count under the exhausted address
        and get 429 until the window ended; the issued-key list tells it apart
        without a lookup per forged key, even when the key was issued after
        the list was last loaded.
        """
        # A fresh worker, whose issued-key list is due for a load.
        monkeypatch.setattr(limiter_module, '_issued_api_key_buckets', OrderedDict())
        monkeypatch.setattr(middleware, '_issued_list', middleware._nothing_issued)
        monkeypatch.setattr(middleware, '_issued_list_loaded_at', float('-inf'))
        monkeypatch.setattr(middleware, '_issued_list_load', None)
        monkeypatch.setattr(middleware, '_listed_lookups', {})
        monkeypatch.setattr(middleware, '_ISSUED_LIST_REFRESH_SECONDS', 0.05)

        login = {'username': 'nosuch@example.com', 'password': 'wrong'}
        burned = [
            rate_limited_client.post('/api/v1/auth/login', data=login).status_code
            for _ in range(6)
        ]
        assert burned == [401] * 5 + [429]
        forged = [
            rate_limited_client.post(
                '/api/v1/auth/login',
                data=login,
                headers={'X-API-Key': f'{API_KEY_PREFIX}{uuid.uuid4().hex}'},
            ).status_code
            for _ in range(limiter_module._FORGED_LOOKUPS_PER_WINDOW + 5)
        ]
        assert set(forged) == {429}

        # Issued after the forged keys had the list loaded: no list loaded so
        # far names it.
        raw = f'{API_KEY_PREFIX}{uuid.uuid4().hex}'
        db_session.add(
            ApiKey(
                organization_id=test_user.organization_id,
                user_id=test_user.id,
                name='CI',
                hashed_key=hashlib.sha256(raw.encode()).hexdigest(),
                key_prefix=raw[:20],
            )
        )
        db_session.commit()

        statuses = [
            rate_limited_client.post(
                '/api/v1/auth/login', data=login, headers={'X-API-Key': raw}
            ).status_code
            for _ in range(5)
        ]
        assert statuses == [401] * 5

    def test_password_reset_request_429_after_three(self, rate_limited_client):
        """`POST /auth/password-reset/request` is limited to 3/hour by IP."""
        for _ in range(3):
            response = rate_limited_client.post(
                '/api/v1/auth/password-reset/request',
                json={'email': 'flood@example.com'},
            )
            assert response.status_code == 202, response.text

        response = rate_limited_client.post(
            '/api/v1/auth/password-reset/request',
            json={'email': 'flood@example.com'},
        )
        assert response.status_code == 429, response.text

    def test_register_429_after_three(self, rate_limited_client):
        """`POST /auth/register` is limited to 3/hour by IP (existing limit).

               Only the fourth attempt's status is the subject here — the first three
        land on whatever the bootstrap-or-invite gate decides, and the
               limiter has to count them either way.
        """
        for i in range(3):
            response = rate_limited_client.post(
                '/api/v1/auth/register',
                json={
                    'email': f'flood{i}@example.com',
                    'password': 'Password123',
                    'full_name': 'Flood User',
                },
            )
            assert response.status_code != 429, response.text

        response = rate_limited_client.post(
            '/api/v1/auth/register',
            json={
                'email': 'flood4@example.com',
                'password': 'Password123',
                'full_name': 'Flood User',
            },
        )
        assert response.status_code == 429, response.text

    def test_join_organization_429_after_ten_attempts(
        self, rate_limited_client, test_user
    ):
        """`/organizations/join` is limited to 10/hour by caller.

        A wrong code costs nothing and does not consume the invitation, so
        without the cap the 15-minute validity window is a free guessing budget.
        """
        from app.services.token_service import create_access_token

        headers = {
            'Authorization': f'Bearer {create_access_token(data={"sub": str(test_user.id)})}'
        }
        for _ in range(10):
            response = rate_limited_client.post(
                '/api/v1/organizations/join',
                json={'code': 'ZZZZZZZZ'},
                headers=headers,
            )
            assert response.status_code == 404, response.text

        response = rate_limited_client.post(
            '/api/v1/organizations/join', json={'code': 'ZZZZZZZZ'}, headers=headers
        )
        assert response.status_code == 429, response.text

    def test_default_limit_fires_on_an_undecorated_router_route(
        self, rate_limited_client, monkeypatch
    ):
        """the whole point of the router-aware middleware.

        `/auth/init-status` carries no `@limiter.limit` of its own, so only the
        global default protects it. Stock ``SlowAPIMiddleware`` looked the
        endpoint up in `app.routes`, found the `include_router` mount — a node
        with no `endpoint` — and treated every route behind it as exempt, which
        is to say the default limit applied to nothing at all.
        """
        # The default limit is read from settings on each request, so the test
        # sets a small ceiling of its own instead of walking whatever the host
        # stack configured (docker-compose raises it to 5000/minute).
        monkeypatch.setattr(settings, 'RATE_LIMIT_PER_IP', '3/minute')
        allowed = 3

        for i in range(allowed):
            response = rate_limited_client.get('/api/v1/auth/init-status')
            assert response.status_code == 200, f'request {i + 1}: {response.text}'

        response = rate_limited_client.get('/api/v1/auth/init-status')
        assert response.status_code == 429, response.text

    def test_api_root_succeeds_with_limiter_enabled(self, rate_limited_client):
        """`GET /api/` is the only top-level route without `@limiter.exempt`.

        A default-limit provider that slowapi cannot call from the middleware
        turns every one of those requests into a 500.
        """
        response = rate_limited_client.get('/api/')
        assert response.status_code == 200, response.text
        assert response.json()['current_version'] == 'v1'

    def test_slowapi_middleware_is_registered(self):
        """`SlowAPIMiddleware` must be present so default_limits and decorator
        limits are enforced.
        """
        from slowapi.middleware import SlowAPIMiddleware

        assert any(
            isinstance(m.cls, type) and issubclass(m.cls, SlowAPIMiddleware)
            for m in app.user_middleware
        ), (
            'SlowAPIMiddleware is not registered; @limiter.limit decorators and '
            'default_limits will not be enforced. Add app.add_middleware(SlowAPIMiddleware).'
        )


@pytest.mark.integration
class TestScanLookupRateLimit:
    """A worker scanning two codes a second must never meet a refusal."""

    def test_two_scans_a_second_for_a_minute_pass_and_the_next_is_refused(
        self, rate_limited_client, test_user
    ):
        """``GET /labels/scan/{code}`` allows 120 lookups a minute per user.

        One code a second sustained is 60 a minute and two a second for a
        minute is 120, so a window that lets 120 through covers both; the
        121st inside the same window is what stops a camera that keeps
        re-reading one symbol. Every lookup is a different, unknown code: a 404
        is still a lookup, and the allowance is the user's, not the code's.
        """
        from app.services.token_service import create_access_token

        headers = {
            'Authorization': f'Bearer {create_access_token(data={"sub": str(test_user.id)})}'
        }
        statuses = [
            rate_limited_client.get(
                f'/api/v1/labels/scan/NOSUCHCODE{n}', headers=headers
            ).status_code
            for n in range(121)
        ]

        refused = [n for n, code in enumerate(statuses) if code == 429]

        assert refused == [120], (
            'a user has 120 lookups a minute across every code; got refusals '
            f'at {refused} (an empty list means each code counted in a bucket of its own)'
        )


@pytest.mark.integration
class TestLimitsOnRoutesWithAPathParameter:
    """A token or code guessed one value at a time must meet one ceiling."""

    def test_invitation_codes_share_one_ceiling(self, rate_limited_client):
        """``GET /public/invitation/{code}`` allows 30 checks a minute per client.

        Every guess is a different code, hence a different URL. The bucket has
        to belong to the endpoint, not the URL, or each wrong code starts a
        fresh count and the ceiling never meets the guesser.
        """
        statuses = [
            rate_limited_client.get(f'/public/invitation/GUESS{n}').status_code
            for n in range(31)
        ]

        assert [n for n, code in enumerate(statuses) if code == 429] == [30], statuses

    def test_registration_link_tokens_share_one_ceiling(self, rate_limited_client):
        statuses = [
            rate_limited_client.get(
                f'/api/v1/auth/registration-link/guess-{n}'
            ).status_code
            for n in range(31)
        ]

        assert [n for n, code in enumerate(statuses) if code == 429] == [30], statuses

    def test_the_default_limit_counts_across_the_values_of_a_path_parameter(
        self, rate_limited_client, monkeypatch
    ):
        """``GET /items/{item_id}`` carries no limit of its own: only the default.

        Anonymous, so each answer is a 401 whatever the id; the middleware
        counts the request before authentication gets to refuse it.
        """
        monkeypatch.setattr(settings, 'RATE_LIMIT_PER_IP', '3/minute')

        statuses = [
            rate_limited_client.get(f'/api/v1/items/{uuid.uuid4()}').status_code
            for _ in range(4)
        ]

        assert statuses[:3] == [401, 401, 401] and statuses[3] == 429, statuses
