from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.core.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis as RedisClient

logger = get_logger(__name__)

_REDIS_AVAILABLE = False
try:
    import redis.asyncio as _aioredis  # noqa: F401
    from redis.exceptions import RedisError

    _REDIS_AVAILABLE = True
except ImportError:
    pass


class TokenBlacklist:
    """
    Redis-backed JWT access-token blacklist.

    After a successful logout the access token is stored in Redis with a TTL
    equal to the remaining lifetime of the token.  ``get_current_user`` checks
    this store on every request; a revoked token yields a 401 immediately.

    Fail-open / fail-closed behaviour
    ----------------------------------
    In production (``not settings.DEBUG and not settings.TESTING``), every
    check that can deny access fails **closed** — if Redis is unavailable,
    tokens are treated as revoked (access denied).  That covers the explicit
    blacklist (:meth:`is_revoked`), the session-family marker
    (:meth:`is_user_revoked`) and the credential-change marker
    (:meth:`is_issued_before_credential_change`); writers
    (:meth:`revoke`, :meth:`mark_credentials_changed`) raise instead of
    silently dropping a revocation on the floor.  In development and test
    mode the checks fail open to allow running without Redis.

    The credential-change pair used to be the exception — a Redis outage
    right after a password reset quietly resurrected exactly the sessions
    the reset was meant to kill.
    """

    PREFIX = 'token_blacklist:'

    def __init__(self) -> None:
        self._redis: RedisClient | None = None
        # Fail-open mode (no Redis) is checked on every authenticated
        # request — warn once per process instead of per request, otherwise
        # TESTING-mode runs (E2E) drown the logs in identical warnings.
        self._warned_no_redis = False

    def set_redis(self, redis_instance: RedisClient) -> None:
        """Inject the Redis connection (called during app startup)."""
        self._redis = redis_instance
        self._warned_no_redis = False

    def _fail_closed(self) -> bool:
        """Return True when running in production mode (fail-closed)."""
        import os

        from app.config import settings

        testing_env = os.getenv('TESTING', '').lower() == 'true'
        return not settings.DEBUG and not settings.TESTING and not testing_env

    async def revoke(self, token: str, expires_at: datetime) -> None:
        if self._redis is None:
            if self._fail_closed():
                raise RuntimeError(
                    '[TokenBlacklist] Redis unavailable in production — cannot revoke token.'
                )
            logger.warning(
                '[TokenBlacklist] Redis not available – token not revoked (fail-open).'
            )
            return

        now = datetime.now(tz=UTC)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        ttl_seconds = int((expires_at - now).total_seconds())
        if ttl_seconds <= 0:
            return

        try:
            key = f'{self.PREFIX}{token}'
            now_ts = str(int(now.timestamp()))
            # NX, not SETEX: a token already on the list keeps the moment it
            # was first revoked. /auth/refresh forgives a replay arriving
            # within a short grace window measured from that moment, and then
            # revokes the token it was handed — writing a fresh timestamp
            # moved the anchor, so the same stolen cookie replayed every few
            # seconds was forgiven for ever and minted a token pair each time.
            # The entry's TTL was computed from this token's own expiry, so
            # the surviving one already runs out at the right moment.
            first_time = await self._redis.set(key, now_ts, ex=ttl_seconds, nx=True)
            if first_time:
                logger.info('[TokenBlacklist] Token revoked (TTL=%ds).', ttl_seconds)
            else:
                logger.info(
                    '[TokenBlacklist] Token was already revoked — keeping the '
                    'original revocation time.'
                )
        except RedisError as exc:
            if self._fail_closed():
                raise RuntimeError(
                    f'[TokenBlacklist] Failed to revoke token in production: {exc}'
                ) from exc
            logger.error('[TokenBlacklist] Failed to revoke token: %s', exc)

    async def is_revoked(self, token: str) -> bool:
        if self._redis is None:
            if self._fail_closed():
                logger.error(
                    '[TokenBlacklist] Redis unavailable in production – treating token as revoked (fail-closed).'
                )
                return True
            if not self._warned_no_redis:
                logger.warning(
                    '[TokenBlacklist] Redis not available – skipping revocation check (fail-open). '
                    'Logged once per process.'
                )
                self._warned_no_redis = True
            return False

        try:
            key = f'{self.PREFIX}{token}'
            result = await self._redis.exists(key)
            return bool(result)
        except RedisError as exc:
            if self._fail_closed():
                logger.error(
                    '[TokenBlacklist] Error checking token blacklist in production: %s – treating as revoked.',
                    exc,
                )
                return True
            logger.error('[TokenBlacklist] Error checking token blacklist: %s', exc)
            return False

    async def get_revoked_at(self, token: str) -> datetime | None:
        """Return the UTC datetime when *token* was revoked, or ``None``."""
        if self._redis is None:
            return None
        try:
            key = f'{self.PREFIX}{token}'
            val = await self._redis.get(key)
            if val is None:
                return None
            ts = int(val)
            return datetime.fromtimestamp(ts, tz=UTC)
        except (RedisError, ValueError, TypeError, OSError):
            return None

    async def revoke_user_family(self, user_id: str, session_id: str = '') -> None:
        """Revoke all tokens for a user+session pair (reuse detection).

        Stores a session-scoped revocation marker so that only tokens
        within the same session are rejected.  Other sessions belonging
        to the same user are unaffected.

        Fail-closed in production, like its two siblings here. This is the
        write reuse detection makes when it catches a refresh token being
        replayed -- the one moment the system believes it is under attack --
        and returning quietly meant the revocation it must not lose was the
        one it dropped.
        """
        if self._redis is None:
            if self._fail_closed():
                raise RuntimeError(
                    '[TokenBlacklist] Redis unavailable in production — cannot '
                    'revoke the token family after reuse detection.'
                )
            logger.warning(
                '[TokenBlacklist] Redis not available – token family not '
                'revoked (fail-open).'
            )
            return
        try:
            key = (
                f'{self.PREFIX}user:{user_id}:{session_id}'
                if session_id
                else f'{self.PREFIX}user:{user_id}'
            )
            from app.config import settings

            ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
            await self._redis.setex(key, ttl, '1')
            logger.info(
                '[TokenBlacklist] Token family revoked (user_id=%s, session_id=%s).',
                user_id,
                session_id or '*',
            )
        except RedisError as exc:
            if self._fail_closed():
                raise RuntimeError(
                    f'[TokenBlacklist] Failed to revoke the token family in '
                    f'production: {exc}'
                ) from exc
            logger.error('[TokenBlacklist] Failed to revoke family: %s', exc)

    async def mark_credentials_changed(self, user_id: str) -> None:
        """Invalidate every token issued for *user_id* before this moment.

        A password reset must throw out the sessions an attacker may already
        hold. ``revoke_user_family`` cannot express this — its marker
        is a permanent kill switch (nothing clears the user-wide key, and the
        API-key flow honours it), so using it here would lock the user's API
        keys out for the full refresh-token lifetime and would still not
        block ``/auth/refresh``, which only ever consults the *session*-scoped
        key. A timestamp marker cuts exactly the tokens minted before the
        change and lets the very next login work.

        In production a missing marker is not a cosmetic failure — it means
        the reset did not actually invalidate anything, so this raises rather
        than returning quietly. ``revoke`` behaves the same way, and the
        reset flow already lets that exception through.
        """
        if self._redis is None:
            if self._fail_closed():
                raise RuntimeError(
                    '[TokenBlacklist] Redis unavailable in production — cannot '
                    'invalidate sessions after a credential change.'
                )
            logger.warning(
                '[TokenBlacklist] Redis not available – credential change not '
                'recorded, earlier sessions stay valid (fail-open).'
            )
            return
        try:
            from app.config import settings

            ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
            # Sub-second precision on purpose: ``iat`` is whole seconds, so a
            # token minted in the same second as the change still compares as
            # older (fail-closed — the user logs in again a second later).
            now_ts = str(datetime.now(tz=UTC).timestamp())
            await self._redis.setex(f'{self.PREFIX}credchg:{user_id}', ttl, now_ts)
            logger.info(
                '[TokenBlacklist] Credentials changed (user_id=%s) — '
                'earlier tokens invalidated.',
                user_id,
            )
        except RedisError as exc:
            if self._fail_closed():
                raise RuntimeError(
                    f'[TokenBlacklist] Failed to record credential change in '
                    f'production: {exc}'
                ) from exc
            logger.error('[TokenBlacklist] Failed to mark credential change: %s', exc)

    async def is_issued_before_credential_change(
        self, user_id: str, issued_at: float | None
    ) -> bool:
        """True when the credential predates the user's last credential change.

        A token without an ``iat`` claim (issued before this mechanism
        existed) counts as older than any marker.

        ``issued_at`` is a float because not every caller is a JWT: an API key
        knows its creation time to the microsecond, and truncating that to
        whole seconds would refuse a key minted in the same second as the
        marker — fail-closed is right for a token that cannot say when it was
        minted, and wrong for a credential that can.

        An unreadable marker store denies access in production. The
        alternative — answering "not stale" because Redis is down — undoes
        the password-reset guarantee precisely when the incident-response
        path matters most. Only a marker that is *readable and absent*
        means the token survives.
        """
        if self._redis is None:
            if self._fail_closed():
                logger.error(
                    '[TokenBlacklist] Redis unavailable in production – treating '
                    'token as issued before a credential change (fail-closed).'
                )
                return True
            return False
        try:
            raw = await self._redis.get(f'{self.PREFIX}credchg:{user_id}')
        except (RedisError, OSError) as exc:
            if self._fail_closed():
                logger.error(
                    '[TokenBlacklist] Error reading credential-change marker in '
                    'production: %s – treating token as stale.',
                    exc,
                )
                return True
            return False
        if raw is None:
            return False
        try:
            changed_at = float(raw)
        except (TypeError, ValueError):
            # A corrupted marker is indistinguishable from "reset happened,
            # value mangled" — deny in production, ignore in dev.
            return self._fail_closed()
        if issued_at is None:
            return True
        return issued_at < changed_at

    async def is_user_revoked(self, user_id: str, session_id: str = '') -> bool:
        """Check if a user+session token family has been revoked.

        Fails closed in production for the same reason as
        :meth:`is_revoked` — this marker is what refresh-token reuse
        detection acts on, and answering "not revoked" during a Redis
        outage hands a replayed token straight through.
        """
        if self._redis is None:
            if self._fail_closed():
                logger.error(
                    '[TokenBlacklist] Redis unavailable in production – treating '
                    'token family as revoked (fail-closed).'
                )
                return True
            return False
        try:
            key = (
                f'{self.PREFIX}user:{user_id}:{session_id}'
                if session_id
                else f'{self.PREFIX}user:{user_id}'
            )
            return bool(await self._redis.exists(key))
        except RedisError as exc:
            if self._fail_closed():
                logger.error(
                    '[TokenBlacklist] Error checking revoked family in production: '
                    '%s – treating as revoked.',
                    exc,
                )
                return True
            return False

    async def clear_user_family(self, user_id: str, session_id: str = '') -> None:
        """Remove session-family revocation marker (e.g. on successful login)."""
        if self._redis is None:
            return
        try:
            key = (
                f'{self.PREFIX}user:{user_id}:{session_id}'
                if session_id
                else f'{self.PREFIX}user:{user_id}'
            )
            await self._redis.delete(key)
        except RedisError as exc:
            logger.warning(
                'Failed to clear family for %s/%s: %s',
                user_id,
                session_id or '*',
                exc,
            )


# Module-level singleton – imported by auth_service and auth router.
token_blacklist = TokenBlacklist()
