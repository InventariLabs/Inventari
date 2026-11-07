import hashlib
import time
from collections import OrderedDict
from typing import cast

import jwt
from jwt.exceptions import PyJWTError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.core.contracts import API_KEY_HEADER, API_KEY_PREFIX


def _jwt_subject(token: str) -> str | None:
    """Extract the subject from a signed JWT without a DB lookup.

    The signature is verified (cheap HMAC) so a forged token cannot claim an
    arbitrary user bucket; expiry is ignored — an expired-but-authentic token
    still identifies the client for rate limiting.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={'verify_exp': False},
        )
    except PyJWTError:
        return None
    sub = payload.get('sub')
    return str(sub) if sub else None


def _api_key_bucket(raw_key: str) -> str:
    # Hash the raw key so key material never lands in Redis keys.
    return f'apikey:{hashlib.sha256(raw_key.encode()).hexdigest()[:16]}'


# The buckets of the API keys authentication has accepted, the most recent
# last, each with the moment it stops counting. A key header taken on trust is
# a new client per made-up value: rotating unissued keys met a fresh count on
# each one. A key therefore earns a bucket of its own only once
# ``resolve_api_key`` has accepted it — the rate-limit middleware asks it
# before counting a key-shaped credential this process does not know yet
# (``unverified_api_key``), so an issued key has its own allowance from its
# first request on any worker. A refusal forgets the key at once; an accepted
# one is asked about again after the time-to-live, so a revoked or expired key
# stops counting as a client of its own even on routes that never
# authenticate it.
_ISSUED_API_KEYS_REMEMBERED = 10_000
_ISSUED_API_KEY_TTL_SECONDS = 60.0
_issued_api_key_buckets: OrderedDict[str, float] = OrderedDict()


def record_api_key_verdict(raw_key: str, *, issued: bool) -> None:
    """Tell the limiter whether authentication accepted ``raw_key``."""
    bucket = _api_key_bucket(raw_key)
    if not issued:
        _issued_api_key_buckets.pop(bucket, None)
        return
    _issued_api_key_buckets[bucket] = time.monotonic() + _ISSUED_API_KEY_TTL_SECONDS
    _issued_api_key_buckets.move_to_end(bucket)
    while len(_issued_api_key_buckets) > _ISSUED_API_KEYS_REMEMBERED:
        _issued_api_key_buckets.popitem(last=False)


# The database check above is work a sender can ask for with nothing but a
# header, and a refusal is never remembered, so a sender over its allowance
# could keep it going by repeating — or rotating — forged keys. Each sender
# (by address) therefore gets a fixed number of lookups per window, spent when
# one starts and returned if the key proves to be issued; past it, only a key
# on the issued-key list the rate-limit middleware keeps is looked up
# (``app.core.limiter_middleware``), and any other key-shaped credential
# counts under whoever sent it, as any unissued key does. An accepted lookup
# costs nothing of it.
_FORGED_LOOKUPS_PER_WINDOW = 20
_FORGED_LOOKUP_WINDOW_SECONDS = 60.0
_FORGED_LOOKUP_SENDERS_REMEMBERED = 10_000
_forged_lookups: OrderedDict[str, tuple[float, int]] = OrderedDict()


def reserve_api_key_lookup(request: Request) -> bool:
    """Spend one of the sender's lookups, if it has any left.

    The lookup is charged when it starts, not when it is refused: requests
    that are all in flight before the first answer comes back would otherwise
    all pass the check. :func:`refund_api_key_lookup` gives it back when the
    key turns out to be issued.
    """
    sender = get_remote_address(request)
    now = time.monotonic()
    started, count = _forged_lookups.get(sender, (now, 0))
    if now - started >= _FORGED_LOOKUP_WINDOW_SECONDS:
        started, count = now, 0
    if count >= _FORGED_LOOKUPS_PER_WINDOW:
        return False
    _forged_lookups[sender] = (started, count + 1)
    _forged_lookups.move_to_end(sender)
    while len(_forged_lookups) > _FORGED_LOOKUP_SENDERS_REMEMBERED:
        _forged_lookups.popitem(last=False)
    return True


def refund_api_key_lookup(request: Request) -> None:
    """Give back the lookup :func:`reserve_api_key_lookup` charged."""
    sender = get_remote_address(request)
    entry = _forged_lookups.get(sender)
    if entry is not None and entry[1] > 0:
        _forged_lookups[sender] = (entry[0], entry[1] - 1)


def _is_known_issued(raw_key: str) -> bool:
    expires = _issued_api_key_buckets.get(_api_key_bucket(raw_key))
    return expires is not None and expires > time.monotonic()


def _presented_api_key(request: Request) -> tuple[str, str]:
    """The API key a request carries, if any, and its Bearer token."""
    api_key = request.headers.get(API_KEY_HEADER, '').strip()
    auth = request.headers.get('authorization', '')
    token = auth[len('Bearer ') :].strip() if auth.startswith('Bearer ') else ''
    if not api_key and token.startswith(API_KEY_PREFIX):
        api_key = token
    return api_key, token


def unverified_api_key(request: Request) -> str | None:
    """A key-shaped credential this process has no current verdict on.

    Only a value with the issued prefix can be a key at all, so anything else
    is never looked up and simply counts as whoever sent it.
    """
    api_key, _ = _presented_api_key(request)
    if api_key.startswith(API_KEY_PREFIX) and not _is_known_issued(api_key):
        return api_key
    return None


def get_client_key(request: Request) -> str:
    """Rate-limit bucket key: issued API key > JWT user > client IP.

    Behind a reverse proxy the client IP is only correct if the server trusts
    proxy headers — prod gunicorn runs with ``--forwarded-allow-ips`` so
    ``request.client.host`` is the real client, not the Caddy peer.
    """
    api_key, token = _presented_api_key(request)
    if api_key and _is_known_issued(api_key):
        return _api_key_bucket(api_key)
    if token:
        user_id = _jwt_subject(token)
        if user_id:
            return f'user:{user_id}'
    return f'ip:{get_remote_address(request)}'


# Initialize limiter with Redis backend if available, otherwise memory.
# Eviction-critical: prefers the dedicated noeviction instance so an
# allkeys-lru cache flush can never drop rate-limit counters.
#
# The default limit is a provider that takes no argument, read from settings on
# every request. slowapi only feeds a request to a callable limit provider on
# decorated routes; from the middleware, which is where default limits are
# applied, the provider is called without one and a provider taking a ``key``
# argument raises on every request. Per-client differentiation belongs in
# ``key_func`` (the bucket) and in ``@limiter.limit`` on individual endpoints
# (the value). Reading the setting late is also what lets a test set a ceiling
# of its own.
#
# ``key_style='endpoint'`` makes a bucket the client and the handler function,
# not the client and the URL. With the default (``'url'``) every value of a path
# parameter was a URL of its own, so a token or code guessed one value at a time
# met a fresh count on each guess and never reached the ceiling.
def _default_limit() -> str:
    return settings.RATE_LIMIT_PER_IP


limiter = Limiter(
    key_func=get_client_key,
    key_style='endpoint',
    storage_uri=settings.REDIS_CRITICAL_URL or settings.REDIS_URL,
    default_limits=[_default_limit],
    enabled=not (settings.TESTING or settings.LOAD_TESTING),
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Answer a refused request in the envelope every other error uses.

    slowapi's stock handler answers ``{"error": "Rate limit exceeded: ..."}``
    — the only error in the API with a top-level key of its own, so a client
    had to look under two keys to find a refusal's message. The refusal is
    ordinary now: ``{"detail": {"code", "message", "limit"}}``, where ``limit``
    is the ceiling that was hit (``10 per 1 minute``), kept as a field rather
    than only inside the sentence. Whatever headers the limiter is configured
    to add are still added to the refusal.

    Deliberately synchronous: the default limits are enforced from
    ``RouterAwareSlowAPIMiddleware``, whose ``sync_check_limits`` falls back
    to slowapi's own handler for a coroutine handler. An ``async def`` here
    would cover the decorator paths only and leave the middleware answering
    the old shape.

    The language is read from the request, not from ``get_current_lang()``:
    the middleware is the outermost one, so a default limit refuses before
    ``LanguageMiddleware`` has set the request language, and a Polish reader
    past the default ceiling was answered in English.
    """
    from app.i18n.service import get_error_message, get_language_from_accept_header

    lang = get_language_from_accept_header(request.headers.get('accept-language'))
    response = JSONResponse(
        status_code=429,
        content={
            'detail': {
                'code': 'RATE_LIMIT_EXCEEDED',
                'message': get_error_message('rate_limit_exceeded', lang),
                'limit': str(exc.detail),
                'lang': lang,
            }
        },
    )
    return cast(
        Response,
        request.app.state.limiter._inject_headers(
            response, request.state.view_rate_limit
        ),
    )
