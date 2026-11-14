"""The module's tools, registered in one deterministic order.

`tools/list` answers in registration order; the snapshot test pins it so a
renamed or reordered tool is a visible contract change, not a surprise for a
client that cached the catalogue. The read tools come first and the two
guarded writes last, so an agent that only learned the reads sees its
catalogue extended rather than reordered.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from ._items import register_item_tools
from ._locations import register_location_tools
from ._stock import register_stock_tools
from ._writes import register_write_tools


def register_tools(server: MCPServer) -> None:
    register_item_tools(server)
    register_location_tools(server)
    register_stock_tools(server)
    register_write_tools(server)


__all__ = ['register_tools']
