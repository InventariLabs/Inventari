"""The security-header middleware has no tests.

It is the kind of code that keeps passing review because it is short and
obviously right, and then quietly stops sending a header after a refactor.
These tests pin the headers themselves, and — just as important — pin that
they survive on error responses, which take a different path out of the app.
"""

import pytest
from fastapi import status

EXPECTED_HEADERS = {
    'x-content-type-options': 'nosniff',
    'x-frame-options': 'DENY',
    'x-xss-protection': '0',
    'referrer-policy': 'strict-origin-when-cross-origin',
    'permissions-policy': 'camera=(), microphone=(), geolocation=()',
}

# Any public path works; the middleware runs before routing.
PROBE_PATH = '/api/v1/health'


class TestSecurityHeaders:
    @pytest.mark.parametrize(('header', 'value'), EXPECTED_HEADERS.items())
    def test_header_present(self, client, header, value):
        response = client.get(PROBE_PATH)

        assert response.headers[header] == value

    def test_csp_locks_down_the_defaults(self, client):
        csp = client.get(PROBE_PATH).headers['content-security-policy']

        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        # Clickjacking defence for browsers that ignore X-Frame-Options.
        assert "frame-ancestors 'none'" in csp

    def test_headers_survive_on_error_responses(self, client):
        """404s and 401s are exactly when a missing header would go unnoticed."""
        response = client.get('/api/v1/definitely-not-a-route')

        assert response.status_code == status.HTTP_404_NOT_FOUND
        for header, value in EXPECTED_HEADERS.items():
            assert response.headers[header] == value


class TestHsts:
    """HSTS moved to the edge — the Caddyfile sets it for every response the
    site serves. The app must not send it too: a second source for the same
    header reads as a policy anyone can change by patching either place, and
    the value is a commitment browsers cache for a year."""

    def test_never_sent_by_the_application(self, client, monkeypatch):
        from app.config import settings

        for debug in (True, False):
            monkeypatch.setattr(settings, 'DEBUG', debug)

            assert 'strict-transport-security' not in client.get(PROBE_PATH).headers, (
                f'app sent HSTS with DEBUG={debug}'
            )
