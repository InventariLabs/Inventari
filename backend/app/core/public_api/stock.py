"""Module-safe access to stock and stock-lot operations."""

from __future__ import annotations

from collections.abc import AsyncIterator, Collection, Iterable, Sequence
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    PickGroupDTO,
    QuantConsumptionDTO,
    RecordPostDTO,
    ReservationResultDTO,
    ShelfContentsDTO,
    StockLotDetailDTO,
    StockLotDTO,
    StockQuantDTO,
    StockQuantRowDTO,
)


class CoreStockAPI:
    """Public Core API for WMS stock operations."""

    async def take_from_the_records_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        storage_location_id: UUID | None,
        quantity: Decimal,
        lot_id: UUID | None = None,
        owner_id: UUID | None = None,
        *,
        require_active_lot: bool = True,
        any_owner: bool = False,
        removal_strategy: str | None = None,
        user_id: UUID | None = None,
        source_document_id: UUID | None = None,
        history_changes: dict[str, Any] | None = None,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
    ) -> list[QuantConsumptionDTO]:
        """Take ``quantity`` off the records the draw plan names, one write each.

        The draw: planned from the records under the anchors, in the removal
        strategy's order (*removal_strategy* overrides the product's), each
        named record written once. A named ``lot_id`` takes that batch and no
        other — on ``require_active_lot=False`` terms for the door that must
        reach a held batch it already confirmed (a scrap of a recalled batch).
        ``user_id``, ``source_document_id`` and ``history_changes`` travel
        onto each record the plan writes, as the record's own history.

        The owner scope follows the one rule every door answers by (the
        owner comes from the document line — ``docs/subsystems/STOCK.md``):
        a named ``owner_id`` takes only that owner's goods, ``any_owner``
        takes whose goods stand there, and the default (neither) is the
        organization's own — a production run asks with ``any_owner``
        because it consumes what is physically there. With
        *storage_location_id* None it takes from every shelf of the product
        — an ingredient, not an ingredient in a particular place.

        On one shelf a refusal is a ``StockUnavailableError`` (a
        ``ValueError``) whose ``code`` says which: ``NO_STOCK``, ``ALL_HELD``
        or ``NOT_ENOUGH`` — branch on the code, the message is a translated
        sentence. On every shelf it is a ``ValueError`` naming what was asked
        for and what there is. Nothing is written unless the whole of it can
        be.

        The movements off the shelf are written in the same call, one per
        shelf, batch and owner taken, naming ``reference_type`` and
        ``reference_id``; a caller writes none of its own. Returns what was
        taken, grain by grain — the shelf, the batch and the owner.
        """
        from app.services._stock_quant_ops import take_from_the_records_async

        breakdown = await take_from_the_records_async(
            db,
            organization_id,
            product_template_id,
            storage_location_id,
            quantity,
            lot_id=lot_id,
            owner_id=owner_id,
            require_active_lot=require_active_lot,
            any_owner=any_owner,
            removal_strategy=removal_strategy,
            user_id=user_id,
            source_document_id=source_document_id,
            history_changes=history_changes,
            reference_type=reference_type,
            reference_id=reference_id,
        )
        return [
            QuantConsumptionDTO(
                lot_id=c.lot_id,
                consumed=c.consumed,
                location_id=c.storage_location_id,
                owner_id=c.owner_id,
                expiry_date=c.expiry_date,
                record_id=c.record_id,
            )
            for c in breakdown
        ]

    async def plan_draw_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        storage_location_id: UUID | None,
        quantity: Decimal | None,
        *,
        removal_strategy: str | None = None,
        owner_id: UUID | None = None,
        any_owner: bool = False,
        lot_id: UUID | None = None,
        require_active_lot: bool = True,
        by_record: bool = False,
        except_document_id: UUID | None = None,
        among_shelves: Sequence[UUID] | None = None,
    ) -> list[QuantConsumptionDTO]:
        """Plan the draw ``take_from_the_records_async`` would make, read-only.

        Same candidates, same order, same owner and batch rules as the
        taking call, ``removal_strategy`` None included — it follows the
        template's own strategy, exactly as the taking call does — and the
        only difference is that no record changes, so a
        caller can say where a draw *would* come from before the door that
        cannot be undone is opened. A plan that falls short is not refused
        here: it names what there is, and the caller decides what a short
        plan means. *quantity* None plans everything free. A document asking
        what its own hold can still be served from passes itself as
        *except_document_id*: its reservation rows are then not counted
        against it, every other document's still are.

        Returns the take summed per (shelf, batch, owner), in the order
        first drawn on — or, with *by_record*, one entry per stock record in
        the order drawn, each naming its ``record_id``: the record a line
        that must name one would name. The plan takes no anchors: it is a
        forecast of the moment it was read, not a reservation — a shelf it
        names can give its stock to someone else before the taking call runs.
        """
        from app.services._stock_draw import plan_draw_async
        from app.services._stock_quant_ops import _by_grain

        plan = await plan_draw_async(
            db,
            organization_id,
            product_template_id,
            storage_location_id,
            quantity,
            strategy=removal_strategy,
            owner_id=owner_id,
            any_owner=any_owner,
            lot_id=lot_id,
            require_active_lot=require_active_lot,
            except_document_id=except_document_id,
            among_shelves=among_shelves,
        )
        if by_record:
            return [
                QuantConsumptionDTO(
                    lot_id=draw.lot_id,
                    consumed=draw.quantity,
                    location_id=draw.storage_location_id,
                    owner_id=draw.owner_id,
                    record_id=draw.record_id,
                )
                for draw in plan.draws
            ]
        return [
            QuantConsumptionDTO(
                lot_id=lot,
                consumed=taken,
                location_id=shelf,
                owner_id=owner,
            )
            for (shelf, lot, owner), taken in _by_grain(plan.draws).items()
        ]

    @asynccontextmanager
    async def posting_scope_async(self, db: AsyncSession) -> AsyncIterator[None]:
        """The scope an operation that posts many lines runs in.

        Inside it, what every line asks again (the organization, a unit, a
        shelf and its type) is read once, and the rows the posting appends —
        movements, cost layers, record history, the journal — are written as
        sets when the block ends, or earlier if something reads them. The
        block must end before the caller commits. Nesting joins the outer
        block. A document's lines, a count, a production run's draws are the
        callers; a single record's write needs none of it.
        """
        from app.core.posting_batch import posting_batch
        from app.core.read_scope import reference_reads

        with reference_reads(db):
            async with posting_batch(db):
                yield

    @asynccontextmanager
    async def ask_what_each_grain_has_free_once_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> AsyncIterator[None]:
        """A block in which ``post_movement_async`` writes and asks its shortage question once, at the end.

        A pass that moves stock off many lines (a correction, an adjustment)
        has each movement checked, as it is written, that the grain it left
        still covers its reservations. Inside this block the checks wait and
        are answered together, in one read, when it ends normally; the
        refusal is the same ``StockUnavailableError``, raised from the end of
        the block. The block must be left before the caller commits, and a
        grain a later line brought back above zero is not refused for having
        dipped. Nesting joins the outer block.
        """
        from app.services._stock_quant_ops import ask_what_each_grain_has_free_once

        async with ask_what_each_grain_has_free_once(db, organization_id):
            yield

    async def lock_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        keys: Iterable[tuple[UUID, UUID | None]] = (),
        reserved_for_document_id: UUID | None = None,
    ) -> None:
        """Lock every group of stock an operation will write, before the first write.

        An operation that writes more than one group — a document's lines,
        the two ends of a move — calls this first, so that two of them taking
        the same groups in different orders wait for each other instead of
        deadlocking. *keys* are ``(product_template_id, storage_location_id)``;
        a location of ``None`` is every shelf of the product.
        *reserved_for_document_id* adds the groups that document's
        reservations hold. What is locked is each group's anchor, created
        here for a named shelf that has none yet. The lock lasts until the
        transaction ends.
        """
        from app.services._stock_quant_ops import lock_stock_async

        await lock_stock_async(
            db,
            organization_id,
            keys=keys,
            reserved_for_document_id=reserved_for_document_id,
        )

    async def post_movement_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        quantity: Decimal,
        *,
        from_location_id: UUID | None = None,
        to_location_id: UUID | None = None,
        lot_id: UUID | None = None,
        owner_id: UUID | None = None,
        require_active_lot: bool = True,
        reference_type: str,
        reference_id: UUID,
        created_by: UUID | None = None,
        records: Sequence[RecordPostDTO] = (),
    ) -> list[QuantConsumptionDTO]:
        """State the records a movement is and write the movement, together.

        ``stock_moves.create_async`` records a movement and states no
        record. A module that moves stock itself instead of going through the
        record's own posting calls this, so the two cannot disagree.

        *to* alone receives, *from* alone issues, both transfer — the grain
        the caller names: ``lot_id`` (the batch-less stock when None) and
        ``owner_id`` (a consignor's, or without it the organization's own),
        one movement. ``require_active_lot=False`` lets a held batch be
        carried rather than consumed. ``records`` are the records this
        movement is, stated inside the same locks beside the movement.
        Valuation stays with the caller. Raises ``StockUnavailableError``
        (a ``ValueError``) when what leaves would leave the grain's
        reservations uncovered — the caller's transaction then takes it all
        back — and ``TypeError`` when neither location is given.
        """
        from app.services._stock_quant_ops import post_movement_async

        posted = await post_movement_async(
            db,
            organization_id,
            product_template_id,
            quantity,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            lot_id=lot_id,
            owner_id=owner_id,
            require_active_lot=require_active_lot,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=created_by,
            records=records,
        )
        return [
            QuantConsumptionDTO(
                lot_id=p.lot_id,
                consumed=p.consumed,
                location_id=p.storage_location_id,
                owner_id=p.owner_id,
            )
            for p in posted
        ]

    async def get_or_create_lot_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        name: str,
        is_serial: bool = False,
        expiry_date: date | None = None,
        production_date: date | None = None,
        use_by_date: date | None = None,
    ) -> UUID:
        from app.services._stock_lot_ops import get_or_create_lot_async

        lot = await get_or_create_lot_async(
            db,
            organization_id,
            product_template_id,
            name,
            is_serial=is_serial,
            expiry_date=expiry_date,
            production_date=production_date,
            use_by_date=use_by_date,
        )
        return lot.id

    async def list_quants_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID | None = None,
        storage_location_id: UUID | None = None,
        product_template_ids: list[UUID] | None = None,
        storage_location_ids: list[UUID] | None = None,
    ) -> list[StockQuantDTO]:
        from app.services._stock_quant_query import list_quants_async

        # The rows speak the view's columns; the DTO speaks the API's name for
        # the shelf.
        return [
            StockQuantDTO.model_validate(
                {**q._mapping, 'location_id': q.storage_location_id}
            )
            for q in await list_quants_async(
                db,
                organization_id,
                product_template_id,
                storage_location_id,
                product_template_ids,
                storage_location_ids,
            )
        ]

    async def quantities_by_shelf_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        storage_location_ids: list[UUID] | None = None,
    ) -> dict[UUID, dict[UUID, Decimal]]:
        """Shelf -> product -> quantity, batches and owners summed together.

        What a shelf's fill is computed from, summed in the database rather
        than by the caller over ``list_quants_async``: an organization's
        overview has hundreds of thousands of groups. ``storage_location_ids``
        narrows to those shelves; ``None`` reads the whole organization.
        """
        from app.services._stock_quant_query import quantities_by_shelf_async

        return await quantities_by_shelf_async(
            db, organization_id, storage_location_ids
        )

    async def shelf_contents_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_ids: Collection[UUID] = (),
    ) -> list[ShelfContentsDTO]:
        """What stands on every shelf, told in one row per shelf.

        How many products stand there, the one when it is one, and the
        quantities of *product_template_ids*.

        For a reader of a whole floor, which needs a tile per shelf rather
        than every product group on it: ``list_quants_async`` over a floor of
        hundreds of thousands of groups is seconds of rows nobody draws.
        """
        from app.services._stock_quant_query import shelf_contents_async

        return await shelf_contents_async(db, organization_id, product_template_ids)

    async def list_quant_rows_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        product_template_id: UUID | None = None,
        location_id: UUID | None = None,
        lot_id: UUID | None = None,
        include_empty: bool = False,
        search: str | None = None,
        limit: int = 200,
        offset: int = 0,
        count_cap: int | None = None,
    ) -> tuple[list[StockQuantRowDTO], int]:
        """A page of the stock list, and its count (stopped at ``count_cap``)."""
        from app.services.stock_quants_service import list_rows_for_org_async

        return await list_rows_for_org_async(
            db,
            organization_id,
            product_template_id=product_template_id,
            location_id=location_id,
            lot_id=lot_id,
            include_empty=include_empty,
            search=search,
            limit=limit,
            offset=offset,
            count_cap=count_cap,
        )

    async def list_lots_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID | None = None,
    ) -> list[StockLotDTO]:
        from app.services._stock_lot_ops import list_lots_async as svc_list_lots_async

        return [
            StockLotDTO.model_validate(lot)
            for lot in await svc_list_lots_async(
                db, organization_id, product_template_id
            )
        ]

    async def get_lot_detail_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        lot_id: UUID,
    ) -> StockLotDetailDTO | None:
        from app.services._stock_lot_ops import get_lot_detail_async

        return await get_lot_detail_async(db, organization_id, lot_id)

    async def list_lot_rows_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        product_template_id: UUID | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[StockLotDetailDTO], int]:
        from app.services._stock_lot_ops import list_lot_rows_async

        return await list_lot_rows_async(
            db,
            organization_id,
            product_template_id=product_template_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def set_lot_status_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        lot_id: UUID,
        status: str,
        reason: str | None = None,
        user_id: UUID | None = None,
    ) -> StockLotDTO | None:
        from app.services._stock_lot_ops import set_lot_status_async

        lot = await set_lot_status_async(
            db, organization_id, lot_id, status, reason, user_id
        )
        return StockLotDTO.model_validate(lot) if lot is not None else None

    @staticmethod
    def resolve_removal_strategy(
        template: object | None,
        override: str | None = None,
    ) -> str:
        """Pick FIFO/FEFO for a (template, override) pair.

        Thin passthrough to the single implementation in
        ``app.services.stock_strategy`` (the duplicated
        public_api layer is gone). Exposed here so callers can use
        ``core_api.stock.resolve_removal_strategy`` without an extra import.
        """
        from app.services.stock_strategy import resolve_removal_strategy

        return resolve_removal_strategy(cast(Any, template), override=override)

    async def quarantine_lot_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        lot_id: UUID,
        reason: str | None = None,
        *,
        user_id: UUID | None = None,
    ) -> StockLotDTO | None:
        """Set a lot's status to QUARANTINED — blocks consumption/reservation.

        Stock linked to a quarantined lot physically exists but cannot be
        consumed, reserved, or picked until released. Used for quality holds
        (HACCP recall, pharma compliance, safety holds).

        Optionally records the reason in lot ``meta_data``. The hold is
        journalled with the reason, under *user_id* when a person asked for it.
        """
        from app.services._stock_lot_ops import quarantine_lot_async as svc

        lot = await svc(db, organization_id, lot_id, reason, user_id=user_id)
        return StockLotDTO.model_validate(lot) if lot else None

    async def release_lot_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        lot_id: UUID,
        *,
        user_id: UUID | None = None,
    ) -> StockLotDTO | None:
        """Release a quarantined/held lot back to ACTIVE status.

        After release, the lot's stock can be consumed, reserved, and picked
        again. The release is journalled under *user_id*.
        """
        from app.services._stock_lot_ops import release_lot_async as svc

        lot = await svc(db, organization_id, lot_id, user_id=user_id)
        return StockLotDTO.model_validate(lot) if lot else None

    async def reserve_for_document_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        location_id: UUID | None,
        needed_qty: Decimal,
        removal_strategy: str | None = None,
        *,
        document_id: UUID,
        document_line_id: UUID | None = None,
        lot_id: UUID | None = None,
        require_active_lot: bool = True,
    ) -> ReservationResultDTO:
        """Atomically reserve stock for one document, under the groups' anchors.

        Returns a ReservationResultDTO whose slices name a lot, an owner, a
        quantity and the reservation row that records them. Each grain drawn
        on gets that row for the document, naming the group, batch and owner
        it holds, so ``release_for_document_async`` releases this document's
        holds and nobody else's. *removal_strategy* left out follows the
        product's own, the order the draw will take the stock in. *lot_id*
        holds the batch the line names alone; *require_active_lot* False lets that batch be held whatever
        its status, for the door that takes a held batch out by name.
        """
        from app.services._stock_reservation import (
            reserve_for_document_async as reserve,
        )

        return await reserve(
            db,
            organization_id,
            product_template_id,
            location_id,
            needed_qty,
            removal_strategy=removal_strategy,
            document_id=document_id,
            document_line_id=document_line_id,
            lot_id=lot_id,
            require_active_lot=require_active_lot,
        )

    async def held_quantity_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        location_id: UUID | None,
        *,
        document_ids: Sequence[UUID] | None = None,
    ) -> Decimal:
        """How much of this product on this shelf the named documents hold.

        Sums the group's reservation rows, narrowed to one shelf and — when
        *document_ids* is given — to the holds those documents own. Read
        only: a caller telling its own kind of hold (a receipt's quarantine
        hold) apart from the promises other documents made on the same goods
        changes nothing by asking.
        """
        from app.services._stock_reservation import held_quantity_async

        return await held_quantity_async(
            db,
            organization_id,
            product_template_id,
            location_id,
            document_ids=document_ids,
        )

    async def release_unbacked_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        location_id: UUID | None,
        leaving_quantity: Decimal,
        *,
        document_ids: Sequence[UUID] | None = None,
    ) -> Decimal:
        """Release only the hold the remaining stock can no longer cover.

        A group of stock is shared by every record of one product at one
        place, and the reservations on it belong to documents, so stock
        leaving is not a reason to release anything on its own — what stays
        behind usually still covers every hold. Only the part left without
        stock behind it goes, newest hold first.

        *document_ids* narrows the rows that may be released to the holds
        those documents own; every other document's reservation stands, and
        what is free of all of them still decides how much the leaving
        quantity uncovers.

        Returns how much was released.
        """
        from app.services._stock_reservation import release_unbacked_async

        return await release_unbacked_async(
            db,
            organization_id,
            product_template_id,
            location_id,
            leaving_quantity,
            document_ids=document_ids,
        )

    async def release_for_document_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        document_id: UUID,
    ) -> None:
        """Release all reservations for a specific document.

        Deletes the document's reservation rows. Safe for multi-document
        scenarios — only the target document's reservations are released.
        """
        from app.services._stock_reservation import release_for_document_async

        await release_for_document_async(db, organization_id, document_id)

    async def find_best_pick_group_for_picking_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        storage_location_id: UUID | None = None,
        owner_id: UUID | None = None,
        *,
        except_document_id: UUID | None = None,
    ) -> PickGroupDTO | None:
        """The group and lot to plan a picking line from, in the product's removal order.

        Reads availability from the records, names the shelf's anchor and
        the batch, and answers None when no shelf of that product has stock.
        Owner-aware: ``owner_id=None`` (default) considers own stock only.
        A document planning its own picking passes itself as
        *except_document_id*: the stock it holds for its own confirmed lines
        is available to it, every other document's still is not.
        """
        from app.services._stock_quant_query import (
            find_best_pick_group_for_picking_async,
        )

        return await find_best_pick_group_for_picking_async(
            db,
            organization_id,
            product_template_id,
            storage_location_id,
            owner_id,
            except_document_id=except_document_id,
        )
