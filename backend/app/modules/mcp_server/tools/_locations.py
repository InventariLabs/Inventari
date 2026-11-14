"""Location read tools."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

from app.core.public_api import core_api

from .._db import request_session
from .._identity import current_identity, refusal
from .._location_tree import build_tree, list_all_locations
from ..schemas import LocationNode, LocationsResult, LocationTreeResult

_READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True)


def register_location_tools(server: MCPServer) -> None:
    @server.tool(
        name='list_locations',
        title='List locations',
        description=(
            'List the shelves, zones and other locations of this workspace, flat, '
            'in name order, with each location parent_id. Use it to find a shelf '
            'id for search_items, get_stock_levels or get_expiring_soon, or to '
            'see the whole hierarchy as a flat page. Use get_location_tree for '
            'the hierarchy nested. Filter with usage when you only want internal '
            'stock, for example. Example: list_locations(usage="internal").'
        ),
        annotations=_READ_ONLY,
    )
    async def list_locations(
        usage: Annotated[
            str | None,
            Field(
                description='Only locations with this usage (internal, customer, production).'
            ),
        ] = None,
        limit: Annotated[
            int, Field(description='Maximum locations to answer with (1-500).')
        ] = 200,
        offset: Annotated[int, Field(description='How many locations to skip.')] = 0,
    ) -> LocationsResult:
        """List locations flat, with parent ids."""
        identity = current_identity()
        identity.require('locations:read')
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        async with request_session() as db:
            rows = await core_api.locations.list_async(
                db,
                identity.organization_id,
                usage=usage,
                limit=limit,
                offset=offset,
            )
        return LocationsResult(
            locations=[LocationNode.from_dto(row) for row in rows],
            has_more=len(rows) == limit,
        )

    @server.tool(
        name='get_location_tree',
        title='Read the location tree',
        description=(
            'Read locations as a tree: roots with their children. Without '
            'root_id it is the whole workspace hierarchy; with root_id it is '
            'that location and everything below it, plus its ancestors as a '
            'breadcrumb. Use it when a person says "the cold room" or "aisle 3" '
            'and you need the shelves under it. Example: '
            'get_location_tree(root_id="<a zone id>").'
        ),
        annotations=_READ_ONLY,
    )
    async def get_location_tree(
        root_id: Annotated[
            UUID | None,
            Field(
                description='Read this location and everything below it; omit for the whole tree.'
            ),
        ] = None,
    ) -> LocationTreeResult:
        """Read the location hierarchy, or one subtree with its ancestors."""
        identity = current_identity()
        identity.require('locations:read')
        async with request_session() as db:
            if root_id is not None:
                (
                    subtree,
                    ancestors,
                ) = await core_api.locations.subtree_and_ancestors_async(
                    db, identity.organization_id, root_id
                )
                if not subtree:
                    raise refusal(
                        'LOCATION_NOT_FOUND',
                        'location_not_found',
                        location_id=str(root_id),
                    )
                return LocationTreeResult(
                    roots=build_tree([LocationNode.from_dto(row) for row in subtree]),
                    ancestors=[LocationNode.from_dto(row) for row in ancestors],
                )
            nodes = await list_all_locations(db, identity.organization_id)
        return LocationTreeResult(roots=build_tree(nodes))
