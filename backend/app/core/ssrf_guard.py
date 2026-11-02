"""SSRF protection helpers for outbound URLs.

Validates that user-provided URLs do not target private/loopback/link-local
addresses. Used by webhooks and URL fetchers (e.g., recipe scrapers).

Blocks requests to any address that is not globally routable — private,
loopback, link-local, carrier NAT, benchmarking and every other
special-purpose pool — unless the operator explicitly allows them via
``WEBHOOKS_ALLOW_PRIVATE_NETWORKS``.

DNS hostnames (e.g. ``ha.local``) are resolved and checked at validation
time to mitigate DNS rebinding attacks; a name that does not resolve is
rejected rather than waved through.  httpx will still enforce
timeouts and TLS verification at delivery time.

Self-hosted users often want a local target (Home Assistant on
``192.168.x.x``), but the same image also runs installations with several
organizations, where an organization admin choosing the URL would be aiming
the server at its own network. The default is therefore ``false`` — see
``WEBHOOKS_ALLOW_PRIVATE_NETWORKS`` in ``config.py``, which an operator flips
on a single-tenant install; the refusal on screen says so.
"""

import ipaddress
import socket
from urllib.parse import urlparse

from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger
from app.i18n.service import get_current_lang, get_error_message

logger = get_logger(__name__)

#: Refused on top of "not globally routable". `is_global` says yes to
#: 192.0.0.9 and 192.0.0.10 — the two addresses RFC 7723 and RFC 8880 carved
#: out of IETF protocol assignments as genuinely reachable. They are protocol
#: infrastructure (PCP anycast, NAT64 prefix discovery), never a webhook
#: target, and refusing the whole /24 costs nothing.
_ALWAYS_REFUSED: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network('192.0.0.0/24'),
)

_LOOPBACK_HOSTNAMES = frozenset(['localhost', 'ip6-localhost', 'ip6-loopback'])

_ALLOWED_SCHEMES = ('http', 'https')


class WebhookUrlRejectedError(ValueError):
    """A URL refused by the guard, carrying *why* rather than a sentence.

    The reason is the tail of a ``webhook_url_<reason>`` catalogue key, so the
    message is already in the reader's language when the exception is built
    and callers that want to say it differently (the AI connection form) can
    still branch on :attr:`reason`.
    """

    def __init__(
        self,
        reason: str,
        *,
        host: str,
        resolved: str | None = None,
    ) -> None:
        super().__init__(
            get_error_message(
                f'webhook_url_{reason}',
                get_current_lang(),
                host=host,
                resolved=resolved or '',
            )
        )
        self.reason = reason
        self.host = host
        self.resolved = resolved


def _is_private_ip(raw: str) -> bool:
    """Return True if *raw* is an IP address literal we must not aim the server at.

    The rule is "not globally routable", not a list of ranges. A list was the
    rule until it fell three pools short: 100.64.0.0/10 — the carrier-NAT space
    a Tailscale address comes from — plus 198.18.0.0/15 (benchmarking) and
    192.0.0.0/24 (IETF protocol assignments) all sailed through while
    192.168.0.0/16 was refused. Whether "reach into my house" was allowed
    depended on which flavour of private network the house used, and no message
    could explain the difference because there was no reason behind it.

    ``ipaddress.is_global`` is derived from the IANA special-purpose registries,
    so it covers every such pool at once — including the ones registered after
    this was written, which a list cannot. What it lets through on purpose is
    handled by `_ALWAYS_REFUSED`.

    Handles IPv4, IPv6, and IPv6-mapped IPv4 addresses (e.g. ``::ffff:127.0.0.1``).
    """
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_global or any(ip in net for net in _ALWAYS_REFUSED)


def validate_webhook_url(url: str, allow_private: bool = False) -> str:
    """Validate *url* is safe for outbound webhook delivery.

    Args:
        url: The target URL entered by the user.
        allow_private: When ``True``, allows private/loopback addresses.
            Defaults to ``False`` for security.

    Returns:
        The resolved IP address (pinned to prevent DNS rebinding).

    Raises:
        ValueError: If the URL is malformed, uses a disallowed scheme, or
            targets a private address.
    """
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        logger.warning('Malformed webhook URL: %s', exc)
        raise ServiceRejectionError('webhook_url_malformed') from exc

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ServiceRejectionError(
            'webhook_url_scheme', schemes='/'.join(_ALLOWED_SCHEMES)
        )

    hostname = parsed.hostname
    if not hostname:
        raise ServiceRejectionError('webhook_url_no_hostname')

    if allow_private:
        # Still resolve to pin the IP for consistency, but don't fail if unresolvable
        try:
            addrs = socket.getaddrinfo(
                hostname, parsed.port, socket.AF_UNSPEC, socket.SOCK_STREAM
            )
            return str(addrs[0][4][0]) if addrs else hostname
        except socket.gaierror:
            return hostname

    if hostname.lower() in _LOOPBACK_HOSTNAMES:
        raise WebhookUrlRejectedError(
            'loopback',
            host=hostname,
        )

    if _is_private_ip(hostname):
        raise WebhookUrlRejectedError(
            'private',
            host=hostname,
        )

    # Resolve and pin the IP to prevent DNS rebinding
    try:
        addrs = socket.getaddrinfo(
            hostname, parsed.port, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        # A name we cannot resolve is a rejection, not a free pass.
        # Letting it through left a rebinding window: delivery resolves the
        # name again (``_webhook_delivery.py``), so an attacker controlling
        # the authoritative server could answer NXDOMAIN at validation time
        # and a private address at delivery time.
        raise WebhookUrlRejectedError(
            'unresolved',
            host=hostname,
        ) from exc

    if not addrs:
        raise WebhookUrlRejectedError(
            'unresolved',
            host=hostname,
        )

    pinned_ip = str(addrs[0][4][0])
    if _is_private_ip(pinned_ip):
        raise WebhookUrlRejectedError(
            'rebinding',
            host=hostname,
            resolved=pinned_ip,
        )
    return pinned_ip
