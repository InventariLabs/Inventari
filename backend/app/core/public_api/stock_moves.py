"""Public Core API for explicit WMS stock movement records.

Wraps :mod:`app.services.stock_moves_service` to enforce the
CoreAPI contract: ``db.flush()`` only (no commit), DTO returns,
organization-scoped reads.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    StockAgeBucketDTO,
    StockAgeEntryDTO,
    StockMoveDTO,
    StockMovePostedGroupDTO,
    StockMoveRowDTO,
)
from app.core.public_api._access import reads, writes


class CoreStockMovesAPI:
    """Public Core API namespace for StockMove records."""

    @writes
    async def create_async(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        product_template_id: UUID,
        quantity: Decimal,
        from_location_id: UUID | None = None,
        to_location_id: UUID | None = None,
        lot_id: UUID | None = None,
        owner_id: UUID | None = None,
        state: str = 'done',
        reference_type: str | None = None,
        reference_id: UUID | None = None,
        created_by: UUID | None = None,
        completed_at: datetime | None = None,
    ) -> StockMoveDTO:
        """Create one movement; ``owner_id`` says whose goods moved.

        The one contract every door's movement writes go through
        (``docs/subsystems/STOCK.md`` — the owner comes from the document
        line), so the ledger can say whose goods left the way the
        reservation row and the quant say whose goods stand.
        """
        from app.services.stock_moves_service import create_async as _create

        return await _create(
            db,
            organization_id=organization_id,
            product_template_id=product_template_id,
            quantity=quantity,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            lot_id=lot_id,
            owner_id=owner_id,
            state=state,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=created_by,
            completed_at=completed_at,
        )

    @reads
    async def get_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        move_id: UUID,
    ) -> StockMoveDTO | None:
        from app.services.stock_moves_service import get_async as _get

        return await _get(db, organization_id, move_id)

    @reads
    async def list_by_template_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        *,
        limit: int = 200,
        state: str | None = None,
        since: datetime | None = None,
    ) -> list[StockMoveDTO]:
        from app.services.stock_moves_service import list_by_template_async as _list

        return await _list(
            db,
            organization_id,
            product_template_id,
            limit=limit,
            state=state,
            since=since,
        )

    @reads
    async def list_for_org_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        product_template_id: UUID | None = None,
        location_id: UUID | None = None,
        lot_id: UUID | None = None,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
        user_id: UUID | None = None,
        direction: str | None = None,
        state: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 200,
        offset: int = 0,
        after: tuple[datetime, UUID] | None = None,
        known_total: int | None = None,
    ) -> tuple[list[StockMoveDTO], int]:
        """One page of the movement ledger with the full count beside it.

        ``location_id`` answers for the whole subtree below it; ``direction``
        is one of ``in`` / ``out`` / ``internal``; ``since`` and ``until`` read
        the date the goods moved, not the date the row was written.

        The next page is asked for with the last row of the previous one
        (``after``: the date the goods moved and the id) rather than a larger
        ``offset``, and a caller that kept the count from the first page passes
        it back as ``known_total``.
        """
        from app.services.stock_moves_service import list_for_org_async as _list

        return await _list(
            db,
            organization_id,
            product_template_id=product_template_id,
            location_id=location_id,
            lot_id=lot_id,
            reference_type=reference_type,
            reference_id=reference_id,
            user_id=user_id,
            direction=direction,
            state=state,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
            after=after,
            known_total=known_total,
        )

    @reads
    async def list_rows_for_org_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        product_template_id: UUID | None = None,
        location_id: UUID | None = None,
        lot_id: UUID | None = None,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
        user_id: UUID | None = None,
        direction: str | None = None,
        state: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        exclude_module_contexts: bool = False,
        limit: int = 200,
        offset: int = 0,
        after: tuple[datetime, UUID] | None = None,
        known_total: int | None = None,
        count_up_to: int | None = None,
    ) -> tuple[list[StockMoveRowDTO], int]:
        """The same page as :meth:`list_for_org_async`, read as sentences.

        Each row carries the product, unit, both locations, the batch and the
        person alongside the ids, read in the statement that fetched the row.
        ``count_up_to`` stops the count one row past it; a total above it
        means there are more. ``exclude_module_contexts`` leaves out the
        moves of products whose every record belongs to a vertical module,
        the way the general lists do.
        """
        from app.services.stock_moves_service import list_rows_for_org_async as _list

        return await _list(
            db,
            organization_id,
            product_template_id=product_template_id,
            location_id=location_id,
            lot_id=lot_id,
            reference_type=reference_type,
            reference_id=reference_id,
            user_id=user_id,
            direction=direction,
            state=state,
            since=since,
            until=until,
            exclude_module_contexts=exclude_module_contexts,
            limit=limit,
            offset=offset,
            after=after,
            known_total=known_total,
            count_up_to=count_up_to,
        )

    @reads
    async def list_by_reference_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        reference_type: str,
        reference_id: UUID,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> list[StockMoveDTO]:
        from app.services.stock_moves_service import list_by_reference_async as _list

        return await _list(
            db,
            organization_id,
            reference_type,
            reference_id,
            limit=limit,
            offset=offset,
        )

    @reads
    async def count_by_reference_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        reference_type: str,
        reference_id: UUID,
    ) -> int:
        from app.services.stock_moves_service import count_by_reference_async as _count

        return await _count(db, organization_id, reference_type, reference_id)

    @reads
    async def posted_groups_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        reference_type: str,
        reference_id: UUID,
    ) -> list[StockMovePostedGroupDTO]:
        """Every group of stock one source filled, and when it last filled it.

        The whole grouping, not a page of it: a document correction asks
        whether stock a document posted has since left any of the shelves it
        filled, and a finite page of the newest movements drops the oldest
        group whole — the one whose goods are most likely to have been used.
        """
        from app.services.stock_moves_service import posted_groups_async as _posted

        return await _posted(db, organization_id, reference_type, reference_id)

    @reads
    async def any_departure_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        product_template_id: UUID,
        from_location_id: UUID,
        lot_id: UUID | None,
        owner_id: UUID | None,
        since: datetime,
        excluded_reference_ids: Sequence[UUID] = (),
    ) -> bool:
        """Whether stock left one group after *since*, other than these moves.

        The existence read a correction asks before it undoes a posted line:
        one product, one shelf, one batch and one owner, compared null-safely
        for batch and owner. ``excluded_reference_ids`` names the documents
        that restate the original — its corrections and returns — so their
        movements are not counted as a use of the stock. ``since`` compares
        the moment the row was recorded, the clock the document's own
        arithmetic runs on.
        """
        from app.services.stock_moves_service import any_departure_async as _any

        return await _any(
            db,
            organization_id,
            product_template_id=product_template_id,
            from_location_id=from_location_id,
            lot_id=lot_id,
            owner_id=owner_id,
            since=since,
            excluded_reference_ids=excluded_reference_ids,
        )

    @reads
    async def any_departure_from_groups_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        groups: Sequence[StockMovePostedGroupDTO],
        *,
        excluded_reference_ids: Sequence[UUID] = (),
    ) -> bool:
        """``any_departure_async`` for many posted groups, asked in one statement.

        Each group is read from where it last filled (``to_location_id``,
        ``posted_at``), the shape ``posted_groups_async`` returns. A caller
        undoing a document of many lines asks this once instead of once per
        line.
        """
        from app.services.stock_moves_service import (
            any_departure_from_groups_async as _any,
        )

        return await _any(
            db, organization_id, groups, excluded_reference_ids=excluded_reference_ids
        )

    @reads
    async def list_recent_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        limit: int = 200,
    ) -> list[StockMoveDTO]:
        from app.services.stock_moves_service import list_recent_async as _list

        return await _list(db, organization_id, limit=limit)

    @reads
    async def list_receipts_for_aging_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        *,
        as_of: datetime | None = None,
        limit: int = 1000,
    ) -> list[StockAgeEntryDTO]:
        from app.services.stock_moves_service import (
            list_receipts_for_aging_async as _list,
        )

        return await _list(
            db,
            organization_id,
            product_template_id,
            as_of=as_of,
            limit=limit,
        )

    @reads
    async def aggregate_aging_buckets_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        *,
        as_of: datetime | None = None,
    ) -> list[StockAgeBucketDTO]:
        from app.services.stock_moves_service import (
            aggregate_aging_buckets_async as _agg,
        )

        return await _agg(
            db,
            organization_id,
            product_template_id,
            as_of=as_of,
        )
