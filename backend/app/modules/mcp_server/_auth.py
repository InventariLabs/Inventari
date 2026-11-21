"""API-key authentication for the mounted MCP endpoint.

The MCP transport is an ASGI app, not a FastAPI route, so neither the app's
dependencies nor `require_module` run for it. This middleware is that gate:
it resolves the key through the same identity path every other API-key request
takes (`identity_service.get_current_user`, which includes the
owner-membership check and the credential-change marker), asks for
`mcp_server:use`, refuses a module the organization has switched off, and only
then lets the SDK transport see the request.

The key travels in its own `X-API-Key` header, which Core accepts and the MCP
endpoint therefore does too. `Authorization: Bearer` is still honoured for an
MCP client that can send no other header; Core marks such a request
`Deprecation`, so a client that can send the key's own header is steered to it.

The key's own permission list, the key's organization and the key's actor are
put on an `McpIdentity` for the tool handlers. Nothing about them comes from
the request body.
"""

from __future__ import annotations

from contextlib import aclosing
from uuid import UUID

from mcp.server.transport_security import (
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.contracts import API_KEY_HEADER
from app.core.module_sdk import (
    AppException,
    audit_actor_scope,
    current_actor,
    get_current_lang,
    get_current_user,
    get_current_user_context,
    get_module_error_message,
)
from app.core.public_api import core_api

from ._db import request_session
from ._identity import (
    MODULE_NAME,
    McpIdentity,
    bind_identity,
    reset_identity,
)

_WWW_AUTHENTICATE = {'WWW-Authenticate': 'Bearer realm="inventari-mcp"'}

#: Hosts an installation answers on without asking its organization first.
#: The SDK enables this same local list when it serves a loopback address;
#: the module serves through the host app, so it states the list itself.
_DEFAULT_HOSTS = (
    'localhost',
    'localhost:*',
    '127.0.0.1',
    '127.0.0.1:*',
    '[::1]',
    '[::1]:*',
)
_DEFAULT_ORIGINS = (
    'http://localhost',
    'http://localhost:*',
    'http://127.0.0.1',
    'http://127.0.0.1:*',
    'http://[::1]',
    'http://[::1]:*',
)


def _auth_refusal(
    code: str, key: str, *, status_code: int = 401, **kwargs: object
) -> AppException:
    """A refusal answered at *status_code*.

    Only a 401 carries the Bearer challenge: a key that authenticated but does
    not hold a permission is refused with 403, so a client stops retrying its
    credentials and reads what the message asks for.
    """
    return AppException(
        status_code=status_code,
        code=code,
        message=get_module_error_message(
            MODULE_NAME, key, get_current_lang(), **kwargs
        ),
        headers=_WWW_AUTHENTICATE if status_code == 401 else None,
    )


def _string_list(value: object) -> list[str]:
    """A stored allow-list, ignoring a malformed entry rather than unpacking it."""
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, str) and entry]


def _request_key(request: Request) -> str | None:
    """The key from its own header, or the Bearer form MCP clients default to."""
    own = request.headers.get(API_KEY_HEADER, '').strip()
    if own:
        return own
    header = request.headers.get('authorization', '')
    scheme, separator, value = header.partition(' ')
    if not separator or scheme.lower() != 'bearer':
        return None
    key = value.strip()
    return key or None


async def _transport_security_refusal(
    request: Request, organization_id: UUID
) -> Response | None:
    """Validate Host/Origin with the SDK's transport security and the org's list.

    The SDK app is built before any organization is known, so its own
    transport_security cannot carry a per-organization allow-list. It is built
    with the check disabled and this function runs the SDK's middleware per
    request, after the key has named the organization: the loopback defaults,
    plus whatever the organization saved under `allowed_hosts` /
    `allowed_origins`.
    """
    async with request_session() as db:
        hosts = await core_api.settings.get_async(
            db, organization_id, MODULE_NAME, 'allowed_hosts', []
        )
        origins = await core_api.settings.get_async(
            db, organization_id, MODULE_NAME, 'allowed_origins', []
        )
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[*_DEFAULT_HOSTS, *_string_list(hosts)],
        allowed_origins=[*_DEFAULT_ORIGINS, *_string_list(origins)],
    )
    return await TransportSecurityMiddleware(settings).validate_request(
        request, is_post=request.method == 'POST'
    )


async def authenticate_api_key(
    db: AsyncSession, request: Request, raw_key: str
) -> McpIdentity:
    """Turn a bearer key into the workspace identity of this MCP request."""
    user = await get_current_user(request, token=None, api_key=raw_key, db=db)
    context = await get_current_user_context(current_user=user, db=db)
    if context.organization_id is None:
        raise _auth_refusal('MCP_ORGANIZATION_REQUIRED', 'organization_required')
    if not context.has_permission('mcp_server:use'):
        raise _auth_refusal(
            'MCP_PERMISSION_REQUIRED', 'permission_required', status_code=403
        )
    if not await core_api.organizations.is_module_enabled_async(
        db, context.organization_id, MODULE_NAME
    ):
        raise _auth_refusal('MCP_MODULE_DISABLED', 'module_disabled')
    actor = current_actor()
    return McpIdentity(
        user=context,
        organization_id=context.organization_id,
        user_id=context.id,
        key_prefix=(actor or {}).get('key_prefix', ''),
    )


def _refusal_response(exc: AppException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {'message': exc.detail}
    headers = dict(exc.headers or {})
    if exc.status_code == 401 and 'WWW-Authenticate' not in headers:
        headers.update(_WWW_AUTHENTICATE)
    return JSONResponse(
        status_code=exc.status_code, content={'detail': detail}, headers=headers
    )


class McpAuthMiddleware:
    """Authenticate every HTTP request before it reaches the MCP transport."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get('type') != 'http':
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        raw_key = _request_key(request)
        if raw_key is None:
            await _refusal_response(
                _auth_refusal('MCP_AUTH_REQUIRED', 'auth_required')
            )(scope, receive, send)
            return

        async with aclosing(audit_actor_scope()) as actor_scope:
            await anext(actor_scope)
            async with request_session() as db:
                try:
                    identity = await authenticate_api_key(db, request, raw_key)
                except AppException as exc:
                    await _refusal_response(exc)(scope, receive, send)
                    return
            refusal = await _transport_security_refusal(
                request, identity.organization_id
            )
            if refusal is not None:
                await refusal(scope, receive, send)
                return
            token = bind_identity(identity)
            try:
                await self.app(scope, receive, send)
            finally:
                reset_identity(token)


__all__ = ['McpAuthMiddleware', 'authenticate_api_key']
