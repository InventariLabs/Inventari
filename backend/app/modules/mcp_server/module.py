"""The MCP Server module.

Serves the Model Context Protocol over Streamable HTTP at
`/api/v1/mcp-server/mcp`, authenticated with an `api_keys` key that holds
`mcp_server:use`. The tools read the workspace through CoreAPI; the module
owns no data of its own.
"""

from __future__ import annotations

from app.core.module_sdk import ModuleContext, define_module

from ._http import mcp_http_app
from .router import router

_SETTINGS_SCHEMA = {
    'type': 'object',
    'properties': {
        'allowed_hosts': {
            'type': 'array',
            'items': {'type': 'string'},
            'title_key': 'mcp_server:settings.allowedHosts',
            'description_key': 'mcp_server:settings.allowedHostsDesc',
            'default': [],
        },
        'allowed_origins': {
            'type': 'array',
            'items': {'type': 'string'},
            'title_key': 'mcp_server:settings.allowedOrigins',
            'description_key': 'mcp_server:settings.allowedOriginsDesc',
            'default': [],
        },
    },
}


async def _start_transport(context: ModuleContext) -> None:
    await mcp_http_app.startup()


async def _stop_transport(context: ModuleContext) -> None:
    await mcp_http_app.shutdown()


module = define_module(
    router=router,
    on_startup_async_hook=_start_transport,
    on_shutdown_async_hook=_stop_transport,
    settings_schema=_SETTINGS_SCHEMA,
    default_settings={'allowed_hosts': [], 'allowed_origins': []},
)
