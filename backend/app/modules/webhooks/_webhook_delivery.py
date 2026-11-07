from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_retry import mark_external_effect
from app.core.logging import get_logger
from app.modules.webhooks.models import WebhookEndpoint
from app.modules.webhooks.signing import compute_signature
from app.modules.webhooks.ssrf_guard import validate_webhook_url

from ._webhook_constants import (
    _RESPONSE_BODY_MAX_BYTES,
    DEFAULT_CIRCUIT_BREAKER_THRESHOLD,
    decrypt_secret,
)

logger = get_logger(__name__)

#: The delivery result when the endpoint's signing secret cannot be read. One
#: sentence, so the delivery log, the operator page and the tests read the
#: same one. (Not named ``..._SECRET``: ruff reads that word in a constant
#: name as a hardcoded credential and blocks the commit.)
_UNREADABLE_SIGNING_VALUE = (
    'The signing secret cannot be read — it was written under a different '
    'key (a rotation) or edited in the table. Re-enter it in the endpoint '
    'settings; the delivery is refused rather than sent unsigned.'
)


async def _attempt_delivery(
    webhook: WebhookEndpoint,
    payload_bytes: bytes,
    outbound: dict[str, Any],
    *,
    delivery_id: str,
) -> tuple[bool, int | None, str | None, str | None]:
    # One id per delivery (event × endpoint), minted with the delivery row —
    # NOT per attempt. Every retry of the same delivery carries the same
    # X-Inventari-Delivery so receivers using GitHub-style dedup-by-delivery-id
    # drop the repeat instead of applying the same state change twice; a fresh
    # id per attempt turned that promise into an instruction to double-apply.
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Inventari-Webhooks/1.0',
        'X-Inventari-Event': outbound['event'],
        'X-Inventari-Delivery': delivery_id,
    }

    if webhook.secret:
        try:
            plain_secret = decrypt_secret(webhook.secret)
        except (ValueError, TypeError, PermissionError):
            # PermissionError: the stored value refuses to open — bound to
            # another name, or edited in the table. ValueError/TypeError: the
            # stored text is not something the reader can even take apart.
            plain_secret = ''
        if not plain_secret:
            # An unreadable secret is not an unsigned channel. The value was
            # stored to sign with: signing with the empty string it read back
            # produced a header every receiver reads as valid, and sending
            # the payload unsigned left the receiver — and the circuit
            # breaker, which counted a success — unable to tell this channel
            # from one that never had a secret. Refusing is the only outcome
            # that is neither a lie nor a silence: nothing leaves, the reason
            # travels in the result, and the breaker counts it.
            logger.warning(
                'Webhook %s: the signing secret cannot be read — refusing to '
                'deliver rather than sending it unsigned',
                webhook.id,
            )
            return False, None, None, _UNREADABLE_SIGNING_VALUE
        headers['X-Inventari-Signature-256'] = compute_signature(
            payload_bytes, plain_secret
        )

    try:
        from app.config import settings as app_settings

        allow_private = getattr(app_settings, 'WEBHOOKS_ALLOW_PRIVATE_NETWORKS', False)
        # capture the pinned IP so the actual HTTP request connects to
        # the verified address, preventing a TOCTOU DNS-rebinding window between
        # validate_webhook_url's resolution and httpx's own resolution.
        pinned_ip = validate_webhook_url(str(webhook.url), allow_private=allow_private)
    except ValueError as exc:
        return False, None, None, str(exc)

    try:
        from urllib.parse import urlparse

        parsed = urlparse(str(webhook.url))
        hostname = parsed.hostname or ''
        port = parsed.port
        # Build the request URL against the pinned IP so httpx connects
        # to the verified address (no re-resolution → no DNS-rebinding window).
        # The original hostname is carried via the Host header and via the
        # httpx `extensions` so TLS SNI and certificate validation still work
        # for HTTPS, and virtual-host routing works for HTTP.
        port_suffix = f':{port}' if port else ''
        # An IPv6 literal needs brackets in the URL authority; without them
        # the address is parsed as host:port and the request never leaves.
        host_part = f'[{pinned_ip}]' if ':' in pinned_ip else pinned_ip
        target_url = f'{parsed.scheme}://{host_part}{port_suffix}{parsed.path}'
        if parsed.query:
            target_url += f'?{parsed.query}'
        headers['Host'] = hostname
        # snni_hostname / target_hostname tell httpx which host to use for TLS
        # SNI and Host header normalisation, even though the URL contains the IP.
        request_extensions = {
            'sni_hostname': hostname,
            'target_hostname': hostname,
        }

        # The POST leaves the process — once it has, the request that caused
        # it must not be retried on a database conflict (db_retry).
        # Deliveries normally run after the commit, through the event
        # delivery workers; the mark covers any path that does not.
        mark_external_effect('webhook:delivery')
        async with httpx.AsyncClient(timeout=webhook.timeout_seconds) as client:
            response = await client.request(
                method=webhook.http_method,
                url=target_url,
                content=payload_bytes,
                headers=headers,
                extensions=request_extensions,
            )

        status_code = response.status_code
        body = response.text[:_RESPONSE_BODY_MAX_BYTES]
        is_success = 200 <= status_code < 300
        return (
            is_success,
            status_code,
            body if is_success else None,
            None if is_success else body,
        )

    except httpx.TimeoutException:
        return False, None, None, f'Timeout after {webhook.timeout_seconds}s'
    except httpx.RequestError as exc:
        logger.info('Webhook %s: the request failed: %r', webhook.id, exc)
        return False, None, None, _request_failure_sentence(exc, webhook)


def _request_failure_sentence(exc: httpx.RequestError, webhook: WebhookEndpoint) -> str:
    """Say what went wrong in words for the administrator, not the library's.

    httpx reports a refused or unreachable connection as "All connection
    attempts failed", which names neither the address nor what to check. The
    three causes it stands for are the ones the administrator can act on.
    """
    from urllib.parse import urlparse

    parsed = urlparse(str(webhook.url))
    target = parsed.netloc or str(webhook.url)
    if isinstance(exc, httpx.ConnectError):
        if 'certificate' in str(exc).lower() or 'ssl' in str(exc).lower():
            return (
                f'The connection to {target} was refused over TLS: the '
                "receiver's certificate could not be verified."
            )
        return (
            f'Could not connect to {target}. The address may be wrong, a '
            'firewall may be blocking it, or the receiver may be down.'
        )
    return (
        f'The connection to {target} broke before the receiver answered '
        f'({type(exc).__name__}).'
    )


def _calc_next_retry(attempt: int, webhook: WebhookEndpoint) -> datetime:
    # Add jitter to prevent thundering herd on receiver recovery
    import random

    base = webhook.retry_backoff_seconds * (2 ** (attempt - 1))
    jitter = random.uniform(0, base * 0.25)
    backoff = min(base + jitter, 3600)
    return datetime.now(UTC) + timedelta(seconds=backoff)


async def _breaker_threshold_async(db: AsyncSession, organization_id: UUID) -> int:
    """Read the organization's breaker threshold once, before any probing.

    The value travels down to the tally as an argument because a read
    beside the counter would put a query on the session several
    concurrent deliveries share — the second coroutine to reach it would
    knock the first's delivery out mid-flight. Reading it once at the
    path's entry keeps every probe on the same policy without putting a
    query where coroutines meet.
    """
    from app.core.public_api import core_api

    persisted = await core_api.settings.get_async(
        db, organization_id, 'webhooks', 'circuit_breaker_threshold'
    )
    if isinstance(persisted, int):
        return persisted
    return DEFAULT_CIRCUIT_BREAKER_THRESHOLD


async def _update_stats_after_delivery(
    db: AsyncSession,
    webhook: WebhookEndpoint,
    is_success: bool,
    status_code: int | None,
    threshold: int,
) -> None:
    """Fold one delivery outcome into the endpoint's breaker tally.

    The threshold arrives as a required argument — the value each entry
    path read once before its probing started (``_breaker_threshold_async``).
    Required means no caller can hand the breaker a different policy by
    omitting it, and the tally itself stays free of queries, because the
    dispatch runs several deliveries concurrently on one session. Each
    attempt counts on its own: a retry is as real an HTTP probe as the
    first delivery, and its failure joins the same consecutive tally.
    """

    webhook.last_triggered_at = datetime.now(UTC)
    webhook.last_status_code = status_code

    if is_success:
        # A channel the breaker cut off stays cut off until somebody turns it
        # back on, and the tally is what its card says tripped it. A passing
        # test ping proves the receiver answers; it is not that decision.
        if webhook.auto_disabled_at is None:
            webhook.consecutive_failures = 0
    else:
        webhook.consecutive_failures = (webhook.consecutive_failures or 0) + 1

        # The cut-off is one event. A test ping still reaches a channel the
        # breaker switched off, and each failing one used to journal and
        # announce the same cut-off again; the mark is cleared only when a
        # person turns the channel back on, which opens the next one.
        if (
            webhook.consecutive_failures >= threshold
            and webhook.auto_disabled_at is None
        ):
            webhook.is_active = False
            webhook.auto_disabled_at = datetime.now(UTC)
            logger.warning(
                'Webhook "%s" (id=%s) auto-disabled after %d consecutive failures.',
                webhook.name,
                webhook.id,
                webhook.consecutive_failures,
            )
            try:
                await _log_circuit_breaker(db, webhook)
            except Exception:  # best-effort secondary action
                logger.exception('Failed to journal the circuit-breaker cut-off')
            try:
                await _notify_circuit_breaker(db, webhook)
            except Exception:  # best-effort secondary action
                logger.exception('Failed to send circuit-breaker notification')


async def _log_circuit_breaker(db: AsyncSession, webhook: WebhookEndpoint) -> None:
    """Record the cut-off as what it is: an act of the system, not a person.

    ``user_id=None`` is the difference the journal shows — nobody switched
    this channel off, the breaker did, after the endpoint stopped answering.
    Without the entry, a channel that went quiet by itself and one somebody
    turned off looked the same from the outside.
    """
    from app.core.contracts import AuditAction, AuditTargetType
    from app.core.public_api import core_api

    await core_api.audit_log.log_action_async(
        db,
        organization_id=webhook.organization_id,
        user_id=None,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.WEBHOOK_ENDPOINT,
        target_id=webhook.id,
        snapshot={'name': webhook.name, 'url': str(webhook.url)},
        reason='circuit_breaker',
        meta_data={
            # The same structured actor the API-key entries carry: the row
            # says who acted, not only who did not. A null account used to
            # read on the screen as an unknown user; this says the system
            # did it, which is the truth and reads as one.
            'actor': {'type': 'system'},
            'consecutive_failures': webhook.consecutive_failures,
            'auto_disabled': True,
        },
    )


async def _notify_circuit_breaker(db: AsyncSession, webhook: WebhookEndpoint) -> None:
    try:
        from app.core.public_api import core_api

        from . import _notification_labels as _labels

        notifications = await core_api.notifications.notify_org_admins_async(
            db,
            webhook.organization_id,
            title=core_api.notifications.localize(
                _labels.AUTO_DISABLED_TITLE, name=webhook.name
            ),
            content=core_api.notifications.localize(
                _labels.AUTO_DISABLED_CONTENT,
                name=webhook.name,
                failures=webhook.consecutive_failures,
            ),
            notification_type='warning',
            # The notice says to fix the address and switch the channel back
            # on — both happen on this screen.
            link='/settings/webhooks',
        )
        await core_api.notifications.publish_async(db, notifications)
    except AttributeError:
        pass
