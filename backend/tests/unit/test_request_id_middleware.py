"""Tests for RequestIDMiddleware.

Verifies:
1. X-Request-ID is generated when not provided.
2. X-Request-ID is propagated when provided by the client.
3. request_id contextvar is set during the request (log correlation).
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app._middleware import RequestIDMiddleware
from app.core._request_id import get_request_id, request_id_var


async def _handler(request):
    """Return the request_id visible inside the request scope."""
    rid = get_request_id()
    return JSONResponse({'request_id': rid})


def _make_app():
    app = Starlette(routes=[Route('/test', _handler)])
    app.add_middleware(RequestIDMiddleware)
    return app


@pytest.mark.unit
class TestRequestIDMiddleware:
    def test_generates_id_when_not_provided(self):
        """No X-Request-ID header → server generates one, returns it."""
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get('/test')
        assert resp.status_code == 200
        rid = resp.headers.get('x-request-id')
        assert rid is not None
        assert len(rid) == 32  # UUID4 hex
        assert resp.json()['request_id'] == rid

    def test_propagates_provided_id(self):
        """Client sends X-Request-ID → server reuses it."""
        app = _make_app()
        custom_id = 'my-correlation-id-123'
        with TestClient(app) as client:
            resp = client.get('/test', headers={'X-Request-ID': custom_id})
        assert resp.status_code == 200
        assert resp.headers['x-request-id'] == custom_id
        assert resp.json()['request_id'] == custom_id

    def test_contextvar_reset_after_request(self):
        """After the request completes, request_id_var should be None."""
        app = _make_app()
        with TestClient(app) as client:
            client.get('/test')
        assert request_id_var.get() is None

    def test_empty_header_generates_new_id(self):
        """Empty X-Request-ID → treated as missing, new ID generated."""
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get('/test', headers={'X-Request-ID': ''})
        assert resp.status_code == 200
        rid = resp.headers['x-request-id']
        assert len(rid) == 32  # generated, not empty
