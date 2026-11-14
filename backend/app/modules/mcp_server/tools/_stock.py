"""Stock-level and expiry read tools."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

from app.core.module_sdk import effective_expiry
from app.core.public_api import core_api

from .._db import request_session
from .._identity import current_identity, refusal
from ..schemas import (
    ExpiringItem,
    ExpiringSoonResult,
    ExpiryBucketView,
    LotsResult,
    LotView,
    ShelfTotal,
    StockLevelRow,
    StockLevelsResult,
)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True)
_EXPIRY_LOOKUP_CAP = 500


def register_stock_tools(server: MCPServer) -> None:
    @server.tool(
        name='get_stock_levels',
        title='Read stock levels',
        description=(
            'Read quantities per product, shelf and batch. Narrow by product '
            'template, or by shelf. A shelf with no product filter answers '
            'per-product totals for the whole shelf; otherwise every quant row '
            'is returned (one row per product/batch/owner). Use search_items '
            'when you are looking for a record to act on; use this when you '
            'need the numbers. Example: get_stock_levels(shelf_id="<id>").'
        ),
        annotations=_READ_ONLY,
    )
    async def get_stock_levels(
        product_template_id: Annotated[
            UUID | None,
            Field(description='Only this product template.'),
        ] = None,
        shelf_id: Annotated[
            UUID | None,
            Field(description='Only this shelf; alone, it answers per-product totals.'),
        ] = None,
        limit: Annotated[
            int, Field(description='Maximum quant rows to answer with (1-1000).')
        ] = 200,
    ) -> StockLevelsResult:
        """Read quant rows, or per-product totals for one shelf."""
        identity = current_identity()
        identity.require('items:read')
        limit = max(1, min(limit, 1000))
        async with request_session() as db:
            if shelf_id is not None and product_template_id is None:
                totals = await core_api.stock.quantities_by_shelf_async(
                    db, identity.organization_id, [shelf_id]
                )
                shelf_totals = [
                    ShelfTotal(
                        location_id=shelf_id,
                        product_template_id=template_id,
                        quantity=quantity,
                    )
                    for template_id, quantity in totals.get(shelf_id, {}).items()
                ]
                return StockLevelsResult(
                    shelf_totals=shelf_totals, total=len(shelf_totals)
                )
            quants = await core_api.stock.list_quants_async(
                db,
                identity.organization_id,
                product_template_id=product_template_id,
                storage_location_id=shelf_id,
            )
        return StockLevelsResult(
            rows=[
                StockLevelRow(
                    product_template_id=quant.product_template_id,
                    location_id=quant.location_id,
                    lot_id=quant.lot_id,
                    owner_id=quant.owner_id,
                    quantity=quant.quantity,
                    reserved_quantity=quant.reserved_quantity,
                    available_quantity=quant.available_quantity,
                )
                for quant in quants[:limit]
            ],
            total=len(quants),
            has_more=len(quants) > limit,
        )

    @server.tool(
        name='list_lots',
        title='List batches',
        description=(
            'List batches with their status and dates (use_by_date, expiry_date, '
            'production_date), newest first, or read one batch by lot_id. FEFO '
            'reads use_by_date before expiry_date. Use it for a recall or before '
            'choosing stock to issue. Example: list_lots(status="quarantined").'
        ),
        annotations=_READ_ONLY,
    )
    async def list_lots(
        lot_id: Annotated[
            UUID | None, Field(description='Read this batch instead of listing.')
        ] = None,
        product_template_id: Annotated[
            UUID | None, Field(description='Only batches of this product template.')
        ] = None,
        status: Annotated[
            str | None,
            Field(
                description='Only batches in this state: active, quarantined, held, expired, recalled.'
            ),
        ] = None,
        limit: Annotated[
            int, Field(description='Maximum batches per page (1-200).')
        ] = 50,
        offset: Annotated[int, Field(description='How many batches to skip.')] = 0,
    ) -> LotsResult:
        """List batches, or read one."""
        identity = current_identity()
        identity.require('items:read')
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        async with request_session() as db:
            if lot_id is not None:
                detail = await core_api.stock.get_lot_detail_async(
                    db, identity.organization_id, lot_id
                )
                if detail is None:
                    raise refusal('LOT_NOT_FOUND', 'lot_not_found', lot_id=str(lot_id))
                return LotsResult(detail=LotView.from_dto(detail))
            rows, total = await core_api.stock.list_lot_rows_async(
                db,
                identity.organization_id,
                product_template_id=product_template_id,
                status=status,
                limit=limit,
                offset=offset,
            )
        return LotsResult(items=[LotView.from_dto(row) for row in rows], total=total)

    @server.tool(
        name='get_expiring_soon',
        title='Read expiring stock',
        description=(
            'List stock expiring within N days (default 7), earliest first, with '
            'how many days are left. Also '
            'returns the workspace six-bucket expiry forecast, and, when a shelf '
            'is named, how many items expire there in the window. Use it for "what '
            'should we use first" and for waste checks. Example: '
            'get_expiring_soon(days=3).'
        ),
        annotations=_READ_ONLY,
    )
    async def get_expiring_soon(
        days: Annotated[
            int, Field(description='Window length in days from today (0-365).')
        ] = 7,
        shelf_id: Annotated[
            UUID | None, Field(description='Only this shelf, and count it.')
        ] = None,
        limit: Annotated[
            int, Field(description='Maximum rows to answer with (1-200).')
        ] = 50,
    ) -> ExpiringSoonResult:
        """List stock expiring in the next *days* days, with the forecast."""
        identity = current_identity()
        identity.require('items:read')
        days = max(0, min(days, 365))
        limit = max(1, min(limit, 200))
        async with request_session() as db:
            today = await core_api.organizations.today_async(
                db, identity.organization_id
            )
            # The window is a filter on the query, not a cut of a capped list:
            # a workspace whose oldest rows are already expired used to spend
            # the whole cap on them and answer an empty window.
            rows = await core_api.items.list_by_expiry_async(
                db,
                identity.organization_id,
                location_id=shelf_id,
                order='asc',
                expiry_after=today,
                expiry_before=today + timedelta(days=days),
                limit=_EXPIRY_LOOKUP_CAP,
            )
            # The window is the effective expiry — the batch date or the
            # opened package's use-by, whichever is earlier — because that is
            # what the query filtered on and what the provider's screens,
            # forecast and GET /items/expiring report. Judging by the raw
            # batch date here dropped an opened jar whose use-by was inside
            # the window while the same answer's forecast counted it.
            window_end = today + timedelta(days=days)
            items = []
            for item in rows:
                expiry = effective_expiry(item.expiry_date, item.meta_data)
                if expiry is None or not today <= expiry <= window_end:
                    continue
                items.append(
                    ExpiringItem(
                        item_id=item.id,
                        name=item.name,
                        quantity=item.quantity,
                        uom_symbol=item.uom_symbol,
                        shelf_id=item.location_id,
                        shelf_name=item.location_name,
                        expiry_date=expiry,
                        days_left=(expiry - today).days,
                        lot_id=item.lot_id,
                    )
                )
                if len(items) == limit:
                    break
            forecast = await core_api.queries.get_expiry_forecast_async(
                db, identity.organization_id
            )
            shelf_count = None
            if shelf_id is not None:
                shelf_count = await core_api.locations.count_expiring_soon_async(
                    db, identity.organization_id, shelf_id, days=days
                )
        return ExpiringSoonResult(
            days=days,
            today=today,
            items=items,
            forecast=[
                ExpiryBucketView(period=bucket.period, count=bucket.count)
                for bucket in forecast
            ],
            shelf_id=shelf_id,
            shelf_count=shelf_count,
        )
