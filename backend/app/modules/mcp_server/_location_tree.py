"""The location hierarchy shared by the tree tool and the tree resource.

Both readers answer the same shape from the same CoreAPI listing, so the read
and the nesting live here once: a page boundary must not make one of them a
smaller tree than the other.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from .schemas import LocationNode

#: The CoreAPI page size. The tree is answered whole, so the reader pages until
#: the source runs out; the number only bounds one request.
_PAGE = 500


async def list_all_locations(
    db: AsyncSession, organization_id: UUID
) -> list[LocationNode]:
    """Every visible location of the workspace, past the CoreAPI's page cap.

    A tree built from one page is silently missing what sorted after it — the
    reader asked for the workspace, and a partial answer with no marker reads as
    the whole one.
    """
    nodes: list[LocationNode] = []
    offset = 0
    while True:
        rows = await core_api.locations.list_async(
            db, organization_id, limit=_PAGE, offset=offset
        )
        nodes.extend(LocationNode.from_dto(row) for row in rows)
        if len(rows) < _PAGE:
            return nodes
        offset += _PAGE


def build_tree(nodes: list[LocationNode]) -> list[LocationNode]:
    """Turn a flat, name-ordered location list into roots with subtrees.

    A location whose parent is not in the list (an archived ancestor, or a
    subtree read that starts below it) is a root of what was read: the reader
    asked for these locations, and dropping them would make the answer a
    silently smaller tree.
    """
    by_id = {node.id: node for node in nodes}
    roots: list[LocationNode] = []
    for node in nodes:
        parent = by_id.get(node.parent_id) if node.parent_id is not None else None
        if parent is None or parent is node:
            roots.append(node)
        else:
            parent.children.append(node)
    return roots
