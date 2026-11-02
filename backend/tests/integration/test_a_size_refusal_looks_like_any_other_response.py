"""A refusal for size carries the same envelope as every other answer.

The gate used to sit outside every layer that decorates a response, so its
413 left the application wearing nothing but ``content-type``: no CORS
headers, no security headers. A browser on an allowed origin could not even
see the 413 — without CORS headers the fetch fails as a network error, and
"the file is too large" never reaches the user; the performance log, fed by
the app's doomed inner response, reported a status that never hit the wire.

The fix is the stack order, not header duplication: the gate is added
first, so it sits innermost and its answer flows back out through CORS,
the security headers and the performance log like any other response.
These tests hold that order in place.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from app._middleware import BodySizeLimitMiddleware
from app.config import settings
from app.core.security_headers import SecurityHeadersMiddleware
from app.main import app

OVER_LIMIT_BODY = b'x' * 2048


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """The real middleware stack with a small ceiling, so tests stay fast.

    The gate reads ``MAX_REQUEST_BODY_SIZE`` per request, so shrinking it
    here exercises the same refusal a 52 MB upload gets in production
    without moving megabytes around.
    """
    monkeypatch.setattr(settings, 'MAX_REQUEST_BODY_SIZE', 1024)
    return TestClient(app)


class TestASizeRefusalLooksLikeAnyOtherResponse:
    def test_a_declared_oversize_answers_413_with_full_envelope(self, client):
        response = client.post(
            '/api/v1/items/',
            content=OVER_LIMIT_BODY,
            headers={'Origin': settings.FRONTEND_URL},
        )

        assert response.status_code == 413
        assert response.headers['access-control-allow-origin'] == (
            settings.FRONTEND_URL
        )
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['x-frame-options'] == 'DENY'
        assert 'content-security-policy' in response.headers

    def test_a_chunked_oversize_gets_the_same_headers(self, client):
        def chunks():
            for _ in range(4):
                yield b'x' * 1024

        response = client.post(
            '/api/v1/items/',
            content=chunks(),
            headers={'Origin': settings.FRONTEND_URL},
        )

        assert response.status_code == 413
        assert response.headers['access-control-allow-origin'] == (
            settings.FRONTEND_URL
        )
        assert response.headers['x-content-type-options'] == 'nosniff'

    def test_the_gate_answers_before_the_route_its_dependencies(self, client):
        """The refusal is the gate's, not the route's: no auth headers, so a
        401 here would mean the body got past the size check."""
        response = client.post('/api/v1/items/', content=OVER_LIMIT_BODY)

        assert response.status_code == 413
        assert response.json() == {'detail': 'Request body too large'}


def test_the_gate_sits_inside_the_layers_that_decorate_responses() -> None:
    """First added sits innermost. The gate must be inner to CORS, the
    security headers and the performance log — a reorder that puts it back
    on the outside silently strips its refusals of every header those
    layers add."""
    classes = [middleware.cls for middleware in app.user_middleware]
    gate = classes.index(BodySizeLimitMiddleware)

    for decorator in (CORSMiddleware, SecurityHeadersMiddleware):
        assert classes.index(decorator) < gate, (
            f'{decorator.__name__} must sit outside {BodySizeLimitMiddleware.__name__} '
            'so a size refusal still passes through it'
        )
