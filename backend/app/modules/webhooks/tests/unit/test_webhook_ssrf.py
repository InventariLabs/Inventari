"""Unit tests for webhook SSRF protection helpers."""

from collections.abc import Iterator

import pytest

from app.core.exceptions import ServiceRejectionError
from app.core.ssrf_guard import WebhookUrlRejectedError
from app.i18n.service import get_error_message, set_current_lang
from app.modules.webhooks.ssrf_guard import validate_webhook_url


class TestSSRFGuard:
    """Tests for the SSRF guard helper."""

    # ------------------------------------------------------------------
    # Scheme validation
    # ------------------------------------------------------------------

    def test_a_malformed_url_is_refused_without_urlparse_text(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            validate_webhook_url('http://[::1', allow_private=False)
        assert 'not a valid web address' in str(excinfo.value)
        assert 'IPv6' not in str(excinfo.value)

    def test_rejects_non_http_scheme(self) -> None:
        with pytest.raises(ValueError, match='http'):
            validate_webhook_url('ftp://example.com/hook', allow_private=False)

    def test_rejects_file_scheme(self) -> None:
        with pytest.raises(ValueError):
            validate_webhook_url('file:///etc/passwd', allow_private=False)

    # ------------------------------------------------------------------
    # Private IPs blocked when allow_private=False
    # ------------------------------------------------------------------

    def test_blocks_loopback_ip(self) -> None:
        with pytest.raises(ValueError, match='not publicly routable'):
            validate_webhook_url('http://127.0.0.1/hook', allow_private=False)

    def test_blocks_rfc1918_10_range(self) -> None:
        with pytest.raises(ValueError, match='not publicly routable'):
            validate_webhook_url('http://10.0.0.1/hook', allow_private=False)

    def test_blocks_rfc1918_172_range(self) -> None:
        with pytest.raises(ValueError, match='not publicly routable'):
            validate_webhook_url('http://172.16.5.5/hook', allow_private=False)

    def test_blocks_rfc1918_192_range(self) -> None:
        with pytest.raises(ValueError, match='not publicly routable'):
            validate_webhook_url('http://192.168.1.1/hook', allow_private=False)

    def test_blocks_link_local(self) -> None:
        with pytest.raises(ValueError, match='not publicly routable'):
            validate_webhook_url('http://169.254.1.1/hook', allow_private=False)

    def test_blocks_localhost_hostname(self) -> None:
        with pytest.raises(WebhookUrlRejectedError) as excinfo:
            validate_webhook_url('http://localhost/hook', allow_private=False)
        assert excinfo.value.reason == 'loopback'

    def test_blocks_ipv6_loopback(self) -> None:
        with pytest.raises(ValueError, match='not publicly routable'):
            validate_webhook_url('http://[::1]/hook', allow_private=False)

    # ------------------------------------------------------------------
    # Accepted URLs (parametrized)
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        ('url', 'allow_private'),
        [
            ('http://example.com/hook', False),
            ('https://example.com/hook', False),
            ('http://192.168.1.100:8123/api/webhook/abc', True),
            ('http://localhost:3000/hook', True),
            ('http://127.0.0.1:8080/hook', True),
            ('https://8.8.8.8/hook', False),
            ('https://discord.com/api/webhooks/123/abc', False),
            ('http://homeassistant.local:8123/api/webhook/abc', True),
        ],
        ids=[
            'accepts-http-scheme',
            'accepts-https-scheme',
            'allows-private-ip-when-flag-set',
            'allows-localhost-when-flag-set',
            'allows-loopback-ip-when-flag-set',
            'allows-public-ip',
            'allows-public-hostname',
            'allows-home-assistant-local-hostname-when-flag-set',
        ],
    )
    def test_accepts_webhook_url(
        self, url: str, allow_private: bool, stub_dns: object
    ) -> None:
        # stub_dns keeps this off the network: validation resolves every
        # hostname, so these cases used to need a working resolver.
        validate_webhook_url(url, allow_private=allow_private)

    # ------------------------------------------------------------------
    # Malformed URLs
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DNS resolution
    # ------------------------------------------------------------------

    def test_rejects_unresolvable_hostname(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A name that does not resolve is a rejection, not a free pass:
        delivery resolves it again, so an attacker owning the authoritative
        server could answer NXDOMAIN here and a private address there."""
        import socket

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise socket.gaierror('Name or service not known')

        monkeypatch.setattr(socket, 'getaddrinfo', _boom)

        with pytest.raises(ValueError, match='could not be resolved'):
            validate_webhook_url('https://nx.example/hook', allow_private=False)

    def test_unresolvable_hostname_still_allowed_when_private_is_allowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Self-hosted installs that opted in keep working offline."""
        import socket

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise socket.gaierror('Name or service not known')

        monkeypatch.setattr(socket, 'getaddrinfo', _boom)

        assert (
            validate_webhook_url('http://ha.local:8123/hook', allow_private=True)
            == 'ha.local'
        )

    def test_rejects_url_without_hostname(self) -> None:
        with pytest.raises(ServiceRejectionError) as excinfo:
            validate_webhook_url('https:///path', allow_private=False)
        assert excinfo.value.key == 'webhook_url_no_hostname'


class TestTheGuardSpeaksTheReadersLanguage:
    """The sentence is built where the guard refuses, in the session's language.

    Pydantic's URL type turns most of these away at the form before the guard
    sees them; the guard is also reached from the AI connection, the recipe
    cover downloader and webhook delivery, which have no such schema in front.
    """

    @pytest.fixture(autouse=True)
    def _polish_session(self) -> Iterator[None]:
        set_current_lang('pl')
        yield
        set_current_lang('en')

    def test_a_scheme_other_than_http_is_said_in_polish(self) -> None:
        with pytest.raises(ServiceRejectionError) as excinfo:
            validate_webhook_url('ftp://example.com/hook', allow_private=False)
        assert str(excinfo.value) == get_error_message(
            'webhook_url_scheme', 'pl', schemes='http/https'
        )
        assert str(excinfo.value).startswith('Dla webhooków')

    def test_a_missing_host_is_said_in_polish(self) -> None:
        with pytest.raises(ServiceRejectionError) as excinfo:
            validate_webhook_url('https:///path', allow_private=False)
        assert str(excinfo.value).startswith('Adres webhooka musi zawierać')

    def test_a_loopback_refusal_names_the_host_in_polish(self) -> None:
        with pytest.raises(WebhookUrlRejectedError) as excinfo:
            validate_webhook_url('http://localhost:9000/hook', allow_private=False)
        assert str(excinfo.value) == get_error_message(
            'webhook_url_loopback', 'pl', host='localhost', resolved=''
        )
        assert 'localhost' in str(excinfo.value)
