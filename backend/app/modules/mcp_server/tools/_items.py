"""Item and batch read tools."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

from app.core.public_api import core_api

from .._db import request_session
from .._identity import current_identity, refusal
from ..schemas import (
    ItemDetail,
    ItemView,
    LotView,
    SearchItemsResult,
    StockRow,
)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True)


def _item_view(item) -> ItemView:
    return ItemView.from_dto(item)


def register_item_tools(server: MCPServer) -> None:
    @server.tool(
        name='search_items',
        title='Search stock',
        description=(
            'Find stock in this workspace by product name, or by a barcode when '
            'the text is one. Returns stock on hand grouped into rows a picker '
            'can choose from; interchangeable records (same product, shelf and '
            'no date or serial) are one row with the total. When nothing is on '
            'hand, returns catalogue records matching the text, so a product '
            'with no stock is still found. Use get_item for one record; use '
            'list_locations first when you need a shelf id. Example: '
            'search_items(query="olive oil").'
        ),
        annotations=_READ_ONLY,
    )
    async def search_items(
        query: Annotated[
            str, Field(description='Product name, or a barcode to look up.')
        ],
        shelf_id: Annotated[
            UUID | None,
            Field(description='Only stock on this shelf (a location id).'),
        ] = None,
        limit: Annotated[
            int, Field(description='Maximum rows to answer with (1-50).')
        ] = 20,
    ) -> SearchItemsResult:
        """Search stock and catalogue records by name or barcode."""
        identity = current_identity()
        identity.require('items:read')
        limit = max(1, min(limit, 50))
        storage_ids = [shelf_id] if shelf_id is not None else None
        async with request_session() as db:
            summary = await core_api.items.search_stock_summary_async(
                db,
                identity.organization_id,
                storage_ids=storage_ids,
                search=query,
                quantity_above=Decimal('0'),
                limit=limit,
            )
            stock = [
                StockRow(
                    **ItemView.from_dto(item).model_dump(),
                    offered_quantity=offered,
                    merged=merged,
                )
                for item, offered, merged in summary
            ]
            records: list[ItemView] = []
            if not stock:
                page = await core_api.items.search_cursor_paginated_async(
                    db,
                    identity.organization_id,
                    storage_ids=storage_ids,
                    search=query,
                    limit=limit,
                )
                records = [_item_view(item) for item in page.items]
            if not stock and not records:
                # A barcode is written on the product, not on every record; the
                # two searches above ask the record name, so the scan code gets
                # one lookup of its own instead of an empty answer.
                item = await core_api.items.find_by_barcode_async(
                    db,
                    identity.organization_id,
                    query,
                    quantity_positive=False,
                )
                if item is not None:
                    records = [_item_view(item)]
        return SearchItemsResult(query=query, stock=stock, records=records)

    @server.tool(
        name='get_item',
        title='Read one stock record',
        description=(
            'Read one stock record by id: quantity, shelf, product, batch, '
            'expiry and namespaced metadata, plus the batch details when the '
            'record names a batch. Use the id from search_items. Refuses when '
            'the record is not in this workspace.'
        ),
        annotations=_READ_ONLY,
    )
    async def get_item(
        item_id: Annotated[UUID, Field(description='The record id from search_items.')],
    ) -> ItemDetail:
        """Read one stock record and, when it has one, its batch."""
        identity = current_identity()
        identity.require('items:read')
        async with request_session() as db:
            item = await core_api.items.get_async(db, identity.organization_id, item_id)
            if item is None:
                raise refusal('ITEM_NOT_FOUND', 'item_not_found', item_id=str(item_id))
            lot = None
            if item.lot_id is not None:
                lot_dto = await core_api.stock.get_lot_detail_async(
                    db, identity.organization_id, item.lot_id
                )
                lot = LotView.from_dto(lot_dto) if lot_dto is not None else None
        return ItemDetail(item=_item_view(item), lot=lot)
