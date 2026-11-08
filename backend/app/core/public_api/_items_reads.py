from __future__ import annotations

import builtins
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import CursorPaginatedDTO, ItemDTO
from app.core.cursor import encode_cursor
from app.core.public_api._access import reads
from app.services.items import (
    barcode_exists_async,
    count_by_org_async,
    distinct_uom_ids_for_template_async,
    existing_item_ids_async,
    get_any_by_id_async,
    get_by_id_async,
    inherited_category_async,
    list_by_org_async,
    list_existing_serials_async,
    search_cursor_paginated_async,
    search_stock_summary_async,
)
from app.services.items._query_get import (
    get_by_id_for_update_async,
    lock_records_async,
)
from app.services.items._query_listing import (
    latest_purchase_prices_async,
    list_by_expiry_async,
    list_expiring_by_template_async,
    list_with_template_async,
)
from app.services.items._query_lookup import (
    find_by_barcode_async,
    find_stock_row_async,
)


class CoreItemsReadMixin:
    """Read-only methods for CoreItemsAPI."""

    @reads
    async def get_async(
        self, db: AsyncSession, organization_id: UUID, item_id: UUID
    ) -> ItemDTO | None:
        item = await get_by_id_async(db, organization_id, item_id)
        if item is None:
            return None
        return ItemDTO.model_validate(item)

    @reads
    async def existing_ids_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        item_ids: set[UUID],
    ) -> set[UUID]:
        """Return the subset of *item_ids* that exist for *organization_id* — one query.

        The write-layer twin of ``get_async``'s existence question: a door
        storing item references refuses unknown ids before the INSERT, and
        asks once for the whole batch instead of per line.
        """
        return await existing_item_ids_async(db, organization_id, item_ids)

    @reads
    async def get_for_update_async(
        self, db: AsyncSession, organization_id: UUID, item_id: UUID
    ) -> ItemDTO | None:
        """Return a single item with row-level lock (SELECT ... FOR NO KEY UPDATE).

        Tier 2 CoreAPI primitive for concurrent workflows (picking scan,
        stock adjustment) that need to prevent two callers from mutating
        the same item at once. The lock is released when the surrounding
        transaction commits/rolls back.
        """
        item = await get_by_id_for_update_async(db, organization_id, item_id)
        if item is None:
            return None
        return ItemDTO.model_validate(item)

    @reads
    async def lock_records_async(
        self, db: AsyncSession, organization_id: UUID, item_ids: Iterable[UUID]
    ) -> None:
        """Take the row locks of *item_ids* in one statement.

        For a document that will ask for each of its lines' records under
        ``get_for_update_async``: those requests are then answered from what
        this read already holds. Ids naming no record are left for that
        request to refuse.
        """
        await lock_records_async(db, organization_id, item_ids)

    @reads
    async def get_any_async(
        self, db: AsyncSession, organization_id: UUID, item_id: UUID
    ) -> ItemDTO | None:
        """Get item including soft-deleted ones (for protocol rendering)."""
        item = await get_any_by_id_async(db, organization_id, item_id)
        if item is None:
            return None
        return ItemDTO.model_validate(item)

    @reads
    async def list_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        storage_location_id: UUID | None = None,
        template_id: UUID | None = None,
        storage_usage: str | None = None,
        category_id: UUID | None = None,
        context_tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> builtins.list[ItemDTO]:
        """List items using an AsyncSession."""
        items = await list_by_org_async(
            db,
            organization_id,
            storage_location_id=storage_location_id,
            template_id=template_id,
            storage_usage=storage_usage,
            category_id=category_id,
            context_tag=context_tag,
            limit=limit,
            offset=offset,
        )
        return [ItemDTO.model_validate(item) for item in items]

    @reads
    async def distinct_uom_ids_for_template_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        template_id: UUID,
    ) -> list[UUID | None]:
        """Every distinct unit the items of one product carry.

        The whole set, one column, no relations — the caller decides what a
        mixture or a single value means.
        """
        return await distinct_uom_ids_for_template_async(
            db,
            organization_id,
            template_id=template_id,
        )

    @reads
    async def count_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        is_deleted: bool = False,
        category_id: UUID | None = None,
        context_tag: str | None = None,
    ) -> int:
        return await count_by_org_async(
            db,
            organization_id,
            is_deleted=is_deleted,
            category_id=category_id,
            context_tag=context_tag,
        )

    @reads
    async def has_active_barcode_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        barcode: str,
    ) -> bool:
        return await barcode_exists_async(db, organization_id, barcode)

    @reads
    async def list_existing_serials_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        serial_numbers: set[str],
    ) -> set[str]:
        return await list_existing_serials_async(db, organization_id, serial_numbers)

    @reads
    async def search_cursor_paginated_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        storage_ids: list[UUID] | None = None,
        storage_id: UUID | None = None,
        search: str | None = None,
        quantity_above: Decimal | None = None,
        cursor_ts: datetime | None = None,
        cursor_id: UUID | None = None,
        limit: int = 50,
    ) -> CursorPaginatedDTO[ItemDTO]:
        """Cursor-paginated items list using keyset pagination on created_at."""
        page = await search_cursor_paginated_async(
            db,
            organization_id,
            storage_ids=storage_ids,
            storage_id=storage_id,
            search=search,
            quantity_above=quantity_above,
            cursor_ts=cursor_ts,
            cursor_id=cursor_id,
            limit=limit + 1,
        )
        has_more = len(page) > limit
        sliced = page[:limit]
        next_cursor = None
        if has_more:
            last = sliced[-1]
            next_cursor = encode_cursor(last.id, last.created_at)
        return CursorPaginatedDTO(
            items=[ItemDTO.model_validate(i) for i in sliced],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    @reads
    async def search_stock_summary_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        storage_ids: list[UUID] | None = None,
        search: str | None = None,
        quantity_above: Decimal | None = None,
        limit: int = 50,
    ) -> list[tuple[ItemDTO, Decimal, bool]]:
        """Stock rows for a picker: distinguishable ones individually,
        interchangeable ones summed per (product, shelf).

        Each triple carries the row DTO, the quantity it offers (the
        record's own, or the group's total), and whether the row is a
        summed group. See the core search for the grouping rule.
        """
        rows = await search_stock_summary_async(
            db,
            organization_id,
            storage_ids=storage_ids,
            search=search,
            quantity_above=quantity_above,
            limit=limit,
        )
        return [
            (ItemDTO.model_validate(item), offered, merged)
            for item, offered, merged in rows
        ]

    @reads
    async def list_expiring_by_template_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        template_ids: set[UUID],
        expiry_after: date,
        expiry_before: date,
    ) -> dict[UUID, list[ItemDTO]]:
        """Load items expiring within a date range, grouped by template_id.

        Used to surface soon-to-expire items for rotation decisions
        (FEFO picking, planner suggestions, recall queries).
        Returns a dict mapping template_id → list of matching ItemDTOs.
        """
        grouped = await list_expiring_by_template_async(
            db,
            organization_id,
            template_ids=template_ids,
            expiry_after=expiry_after,
            expiry_before=expiry_before,
        )
        return {
            tid: [ItemDTO.model_validate(item) for item in items]
            for tid, items in grouped.items()
        }

    @reads
    async def list_by_expiry_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        template_ids: list[UUID] | None = None,
        location_id: UUID | None = None,
        storage_usage: str | None = None,
        order: str = 'asc',
        limit: int = 500,
    ) -> list[ItemDTO]:
        """List active items sorted by ``expiry_date`` (FEFO picking order).

        Tier 2 CoreAPI extension used by recipes picking, planner
        suggestions, and any consumer that needs FEFO-sorted item
        availability.

        Args:
            organization_id: Org scope (mandatory).
            template_ids: Optional filter — restrict to items bound to
                these templates.
            location_id: Optional filter — restrict to one storage location.
            storage_usage: Optional filter — restrict by storage location
                ``usage`` (e.g. ``"INTERNAL"`` for cost estimation that
                excludes customer-side stock).
            order: ``"asc"`` for FEFO (earliest first), ``"desc"`` for LIFO.
            limit: Safety cap (default 500).
        """
        items = await list_by_expiry_async(
            db,
            organization_id,
            template_ids=template_ids,
            location_id=location_id,
            storage_usage=storage_usage,
            order=order,
            limit=limit,
        )
        return [ItemDTO.model_validate(item) for item in items]

    @reads
    async def list_with_template_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        template_ids: list[UUID],
    ) -> dict[UUID, list[ItemDTO]]:
        """Batch-load active items grouped by template_id.

        Tier 2 CoreAPI extension used by recipes availability checks.
        Templates with no matching items map to ``[]``.
        """
        grouped = await list_with_template_async(db, organization_id, template_ids)
        return {
            tid: [ItemDTO.model_validate(item) for item in items]
            for tid, items in grouped.items()
        }

    @reads
    async def latest_purchase_prices_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        template_ids: builtins.list[UUID],
    ) -> dict[UUID, Decimal]:
        """The newest recorded purchase price of each product that has one.

        Independent of the quantity on hand; deleted records do not answer.
        """
        return await latest_purchase_prices_async(db, organization_id, template_ids)

    @reads
    async def inherited_category_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        source_category_id: UUID | None = None,
        template_id: UUID | None = None,
    ) -> UUID | None:
        """The category a new record of this product is filed under.

        The record the caller names answers first — the transfer's source,
        the record a receipt borrows its identity from — and with none, the
        product answers: the category most of its records carry. See
        ``app.services.items._query_lookup.inherited_category_async`` for
        the full rule.
        """
        return await inherited_category_async(
            db,
            organization_id,
            source_category_id=source_category_id,
            template_id=template_id,
        )

    @reads
    async def find_by_barcode_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        barcode: str,
        *,
        quantity_positive: bool = True,
        for_update: bool = False,
    ) -> ItemDTO | None:
        """Return the first item with *barcode* in *organization_id*.

        Tier 2 CoreAPI extension for barcode-based picking workflows.
        Eager-loads ``uom`` and ``storage_location``. Set
        ``quantity_positive=False`` to match depleted stock.
        Pass ``for_update=True`` to acquire a row-level lock for
        concurrent mutation flows.
        """
        item = await find_by_barcode_async(
            db,
            organization_id,
            barcode,
            quantity_positive=quantity_positive,
            for_update=for_update,
        )
        if item is None:
            return None
        return ItemDTO.model_validate(item)

    @reads
    async def find_stock_row_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        barcode: str | None = None,
        template_id: UUID | None = None,
        expiry_date: date | None = None,
        storage_location_id: UUID | None = None,
        lot_id: UUID | None = None,
        owner_id: UUID | None = None,
        for_update: bool = False,
    ) -> ItemDTO | None:
        """Return the record a delivery to this place tops up.

        ``for_update=True`` returns it under its row lock (``FOR NO KEY
        UPDATE``), freshly read — for a delivery that is about to write the
        record's number, so finding it and locking it is one statement.

        The question a receipt asks before it creates anything: is this
        product already on *this shelf*, and if so, which row is it?
        Serialized and module-owned records never answer yes. See
        ``app.services.items._query_lookup.find_stock_row_async`` for the
        full rule, including why the place narrows a template-backed answer
        and not a barcode-owning one.
        """
        item = await find_stock_row_async(
            db,
            organization_id,
            barcode=barcode,
            template_id=template_id,
            expiry_date=expiry_date,
            storage_location_id=storage_location_id,
            lot_id=lot_id,
            owner_id=owner_id,
            for_update=for_update,
        )
        if item is None:
            return None
        return ItemDTO.model_validate(item)
