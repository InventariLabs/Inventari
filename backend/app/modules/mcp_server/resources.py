"""The two read-only resources the module offers.

Resources answer context, not actions: the workspace overview and the location
tree are what an agent reads before choosing a tool. Both obey the same
permission a tool of theirs would: the overview is item data, the tree is
location data.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp_types import Annotations

from app.core.module_sdk import get_current_lang, get_module_error_message
from app.core.public_api import core_api

from ._db import request_session
from ._identity import MODULE_NAME, current_identity
from .schemas import LocationNode, LocationTreeResult


def _resource_refusal(key: str, **kwargs: object) -> ResourceError:
    message = get_module_error_message(MODULE_NAME, key, get_current_lang(), **kwargs)
    return ResourceError(message)


def _tree(nodes: list[LocationNode]) -> list[LocationNode]:
    by_id = {node.id: node for node in nodes}
    roots: list[LocationNode] = []
    for node in nodes:
        parent = by_id.get(node.parent_id) if node.parent_id is not None else None
        if parent is None or parent is node:
            roots.append(node)
        else:
            parent.children.append(node)
    return roots


def register_resources(server: MCPServer) -> None:
    @server.resource(
        'inventari://org/overview',
        name='org-overview',
        title='Workspace overview',
        description=(
            "Inventory health for the key's workspace: number of items and "
            'locations, expiring soon and expired counts, low stock, stock '
            'value and whether the value is a lower bound. Read it before a '
            'broad question about the workspace.'
        ),
        mime_type='application/json',
        annotations=Annotations(audience=['assistant'], priority=0.8),
    )
    async def org_overview() -> dict:
        identity = current_identity()
        try:
            identity.require('items:read')
        except ToolError as exc:
            raise _resource_refusal(
                'insufficient_permission', permission='items:read'
            ) from exc
        async with request_session() as db:
            overview = await core_api.queries.get_overview_async(
                db, identity.organization_id
            )
        return overview.model_dump(mode='json')

    @server.resource(
        'inventari://locations/tree',
        name='locations-tree',
        title='Location tree',
        description=(
            'The workspace location hierarchy: every shelf, zone and room with '
            'its parent, nested into roots. Read it before naming a shelf id in '
            'a tool call.'
        ),
        mime_type='application/json',
        annotations=Annotations(audience=['assistant'], priority=0.6),
    )
    async def locations_tree() -> dict:
        identity = current_identity()
        try:
            identity.require('locations:read')
        except ToolError as exc:
            raise _resource_refusal(
                'insufficient_permission', permission='locations:read'
            ) from exc
        async with request_session() as db:
            rows = await core_api.locations.list_async(
                db, identity.organization_id, limit=500
            )
        return LocationTreeResult(
            roots=_tree([LocationNode.from_dto(row) for row in rows])
        ).model_dump(mode='json')
