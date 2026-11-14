"""The module's one HTTP route: the MCP endpoint under /api/v1/mcp-server/mcp.

A plain Starlette ``Route`` over the SDK's ASGI app, not ``APIRouter.mount``:
a mount at ``/mcp`` answers a POST to the exact advertised URL with a 307 to
``/mcp/``, and an MCP client posts the address it was given. The Route is the
same ASGI app without that redirect; ``AtRootPath`` presents it at the ``/``
path it is built for.
"""

from fastapi import APIRouter
from starlette.routing import Route

from ._auth import McpAuthMiddleware
from ._http import AtRootPath, mcp_http_app

_auth_app = McpAuthMiddleware(mcp_http_app)

router = APIRouter()
router.routes.append(Route('/mcp', endpoint=AtRootPath(_auth_app), methods=['POST']))
