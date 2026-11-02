"""SSRF guard for outbound LLM requests.

The LLM clients build their target URL from ``AiConnection.api_base_url``,
which is user-supplied (the Test-connection endpoint accepts it inline,
before anything is saved). Without a check the server would happily fetch
``http://169.254.169.254/`` or any RFC1918 address and echo the response
body back in the error message — port scanning plus partial exfiltration
from the internal network.

Webhooks already solve this class of problem in :mod:`app.core.ssrf_guard`;
this module is the LLM-side call site, keyed on its own opt-out flag
``LLM_ALLOW_PRIVATE_NETWORKS`` because a local Ollama on
``127.0.0.1:11434`` is a legitimate self-hosting setup.

Validation alone is not enough: between the guard's DNS lookup and httpx's
own lookup the same name can answer differently, so whoever controls the
authoritative server can pass the check with a public address and have the
request delivered to an internal one. :func:`pin_llm_url` closes that
window the way webhook delivery does — the request goes to the address
that was actually vetted, with the hostname carried in the ``Host`` header
and in TLS SNI so virtual hosting and certificate validation keep working.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

from app.core.exceptions import ServiceRejectionError
from app.core.llm.enums import LlmProtocol, protocol_for
from app.core.logging import get_logger
from app.core.ssrf_guard import (
    WebhookUrlRejectedError,
    validate_webhook_url,
)

logger = get_logger(__name__)

#: Where an Anthropic connection naming no address is sent.
_ANTHROPIC_BASE_URL = 'https://api.anthropic.com'


def route_base_url(connection: Any) -> str:
    """The address a client sends *connection*'s requests to.

    One spelling per route: a trailing slash is dropped, and an Anthropic
    connection with no address goes to Anthropic's public API. The clients
    build their URLs from this, and the refusal memory keys its routes on
    it, so a route written two ways is still one route to both.
    """
    base_url = getattr(connection, 'api_base_url', '') or ''
    provider = getattr(connection, 'provider', '') or ''
    if not base_url and protocol_for(provider) == LlmProtocol.ANTHROPIC:
        base_url = _ANTHROPIC_BASE_URL
    return base_url.rstrip('/')


def guard_llm_url(url: str) -> str:
    """Reject *url* when it targets a private/loopback address.

    Returns:
        The resolved IP address, or the hostname itself when private
        networks are allowed and the name does not resolve.

    Raises:
        ServiceRejectionError: If the URL is malformed, uses a disallowed
            scheme, or targets a private address while
            ``LLM_ALLOW_PRIVATE_NETWORKS`` is off. The key — never a
            sentence — names the cause; the catalogue speaks it in the
            request language, so the same refusal reads Polish on a Polish
            screen. Callers let it propagate: the global ValueError handler
            builds the 400 envelope around the key.

    The refusal speaks for the AI connection and only for it. The shared
    validator below this layer phrases its rejections for webhook
    delivery and points at the webhook opt-out flag; a person saving an
    AI connection would be told to flip a switch that has nothing to do
    with what they are configuring. So every refusal is re-said here as
    its own key: an unresolvable name and a private address are different
    causes (a typo against a policy) and get different keys, and the word
    "webhook" leaves this path never.
    """
    from app.config import settings as app_settings

    allow_private = getattr(app_settings, 'LLM_ALLOW_PRIVATE_NETWORKS', False)
    try:
        return validate_webhook_url(url, allow_private=allow_private)
    except WebhookUrlRejectedError as exc:
        if exc.reason == 'unresolved':
            raise ServiceRejectionError(
                'llm_base_url_unresolved', host=exc.host
            ) from exc
        key = (
            'llm_base_url_loopback'
            if exc.reason == 'loopback'
            else 'llm_base_url_private'
        )
        raise ServiceRejectionError(key, host=exc.host) from exc
    except ValueError as exc:
        refused = exc.key if isinstance(exc, ServiceRejectionError) else None
        if refused == 'webhook_url_scheme':
            raise ServiceRejectionError('llm_base_url_scheme') from exc
        if refused == 'webhook_url_no_hostname':
            raise ServiceRejectionError('llm_base_url_no_hostname') from exc
        # The remaining causes (a malformed URL, a shape the shared validator
        # grew since) read as one keyed refusal; the sentence the validator
        # wrote goes to the log, where an operator can act on it.
        logger.warning('AI connection base URL refused before any request: %s', exc)
        raise ServiceRejectionError('llm_base_url_refused') from exc


@dataclass(frozen=True)
class PinnedTarget:
    """Where to send the request, and which name it is really for.

    ``url`` points at the vetted IP address; ``hostname`` is the name the
    user configured. Sending one without the other breaks either the
    security property or the request itself.
    """

    url: str
    hostname: str

    @property
    def extensions(self) -> dict[str, str]:
        """httpx extensions that keep TLS SNI on the original hostname."""
        return {'sni_hostname': self.hostname, 'target_hostname': self.hostname}

    def with_host_header(self, headers: dict[str, str]) -> dict[str, str]:
        """Return *headers* plus the ``Host`` the origin server expects."""
        merged = dict(headers)
        merged['Host'] = self.hostname
        return merged


def pin_llm_url(url: str) -> PinnedTarget:
    """Validate *url* and rewrite it to the address the guard resolved.

    Falls back to the original URL when the guard hands back a hostname
    rather than an address — that happens only on self-hosted installs
    which opted into private networks and use a name the resolver cannot
    answer for, where there is nothing to pin in the first place.
    """
    pinned = guard_llm_url(url)
    parsed = urlparse(url)
    hostname = parsed.hostname or ''

    try:
        literal = f'[{pinned}]' if ip_address(pinned).version == 6 else pinned
    except ValueError:
        return PinnedTarget(url=url, hostname=hostname)

    port_suffix = f':{parsed.port}' if parsed.port else ''
    target = f'{parsed.scheme}://{literal}{port_suffix}{parsed.path}'
    if parsed.query:
        target += f'?{parsed.query}'
    return PinnedTarget(url=target, hostname=hostname)
