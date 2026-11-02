"""Unit tests for client-IP resolution.

The value feeds the failed-login warnings an operator reads during an incident,
so a caller must not be able to write it.
"""

from starlette.requests import Request

from app.core.network import get_client_ip


def _request(headers: dict[str, str] | None = None, client: str | None = '10.0.0.2'):
    scope = {
        'type': 'http',
        'method': 'POST',
        'path': '/api/v1/auth/login',
        'headers': [
            (k.lower().encode('latin-1'), v.encode('latin-1'))
            for k, v in (headers or {}).items()
        ],
        'client': (client, 4567) if client else None,
        'query_string': b'',
    }
    return Request(scope)


class TestGetClientIp:
    def test_uses_the_transport_peer(self):
        assert get_client_ip(_request()) == '10.0.0.2'

    def test_ignores_x_forwarded_for(self):
        """Uvicorn rewrites scope['client'] when the peer is a trusted proxy;
        parsing the header here would trust every caller instead."""
        request = _request(headers={'X-Forwarded-For': '203.0.113.42'})

        assert get_client_ip(request) == '10.0.0.2'

    def test_ignores_forged_chain(self):
        request = _request(
            headers={'X-Forwarded-For': '1.2.3.4, 5.6.7.8', 'X-Real-IP': '9.9.9.9'}
        )

        assert get_client_ip(request) == '10.0.0.2'

    def test_falls_back_when_there_is_no_peer(self):
        assert get_client_ip(_request(client=None)) == 'unknown'
