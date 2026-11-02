"""Network helpers shared across modules."""

from fastapi import Request


def get_client_ip(request: Request) -> str:
    """Client IP as resolved by the ASGI server.

    ``X-Forwarded-For`` is deliberately not read here. Uvicorn's
    ProxyHeadersMiddleware already rewrites ``scope['client']`` from that header
    when the peer is a trusted proxy (gunicorn runs with
    ``--forwarded-allow-ips``), so the value below is the real client behind
    Caddy. Parsing the header in the application instead would trust whatever
    any caller sends — and this IP ends up in the failed-login warnings that an
    operator reads during an incident. The rate limiter resolves its bucket the
    same way (``app.core.limiter``).
    """
    return request.client.host if request.client else 'unknown'
