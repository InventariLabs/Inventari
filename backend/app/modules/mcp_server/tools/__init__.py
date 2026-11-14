"""The module's read tools, registered in one deterministic order.

`tools/list` answers in registration order; the snapshot test pins it so a
renamed or reordered tool is a visible contract change, not a surprise for a
client that cached the catalogue.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from ._items import register_item_tools
from ._locations import register_location_tools
from ._stock import register_stock_tools


def register_tools(server: MCPServer) -> None:
    register_item_tools(server)
    register_location_tools(server)
    register_stock_tools(server)


__all__ = ['register_tools']
