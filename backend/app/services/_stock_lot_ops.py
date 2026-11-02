"""StockLot operations: get-or-create / list / quarantine / release.

Extracted from ``stock_service.py`` — lot lifecycle operations. Kept
separate from the stock writes (``_stock_quant_ops``) because lots have their
own state machine (ACTIVE / QUARANTINED / HELD / RECALLED) and their
lifecycle events drive what a draw may take (quarantined lots block
consumption).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    LotLocationDTO,
    LotStatusEventDTO,
    StockLotDetailDTO,
)
from app.core.public_api import core_api
from app.models.product_template import ProductTemplate
from app.models.stock_lot import LotStatus, StockLot, effective_status_expression
from app.models.stock_quants_from_records import stock_quants_from_records
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User


async def get_or_create_lot_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    name: str,
    is_serial: bool = False,
    expiry_date: date | None = None,
    production_date: date | None = None,
    use_by_date: date | None = None,
) -> StockLot:
    result = await db.scalars(
        select(StockLot).where(
            StockLot.organization_id == organization_id,
            StockLot.product_template_id == product_template_id,
            StockLot.name == name,
        )
    )
    lot = result.first()
    if lot:
        return lot

    lot = StockLot(
        organization_id=organization_id,
        product_template_id=product_template_id,
        name=name,
        is_serial=is_serial,
        expiry_date=expiry_date,
        production_date=production_date,
        use_by_date=use_by_date,
    )
    db.add(lot)
    await db.flush()
    return lot


async def list_lots_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID | None = None,
) -> list[StockLot]:
    stmt = select(StockLot).where(StockLot.organization_id == organization_id)
    if product_template_id:
        stmt = stmt.where(StockLot.product_template_id == product_template_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _locked_lot_async(
    db: AsyncSession, organization_id: UUID, lot_id: UUID
) -> StockLot | None:
    """The batch whose status is about to change, its row locked first.

    The status read here is journalled as the one the change was made over,
    so a concurrent hold or release is waited for and read, not reported as
    if it had not happened. ``populate_existing`` because a locking select
    otherwise hands back the instance already in the session without its
    columns read again.
    """
    return await db.scalar(
        select(StockLot)
        .where(StockLot.id == lot_id, StockLot.organization_id == organization_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def _journal_status_async(
    db: AsyncSession,
    lot: StockLot,
    previous_status: str,
    *,
    reason: str | None,
    user_id: UUID | None,
) -> None:
    """The journal entry for a batch whose fitness to use was decided.

    Every door that sets a status writes it here, the route and the module
    paths alike: whether a batch may be used is a custody act, and a hold
    raised by code is as much a hold as one a person typed.
    """
    await core_api.audit_log.log_action_async(
        db,
        organization_id=lot.organization_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.STOCK_LOT,
        target_id=lot.id,
        snapshot={
            'lot_name': lot.name,
            'previous_status': previous_status,
            'status': lot.status,
        },
        reason=reason,
    )


async def quarantine_lot_async(
    db: AsyncSession,
    organization_id: UUID,
    lot_id: UUID,
    reason: str | None = None,
    *,
    user_id: UUID | None = None,
) -> StockLot | None:
    """Set a lot's status to QUARANTINED — blocks consumption/reservation/picking.

    Journalled unless it decided nothing: a batch already quarantined, with
    no new reason given, is left as it was.
    """
    lot = await _locked_lot_async(db, organization_id, lot_id)
    if lot is None:
        return None
    previous_status = lot.status
    lot.status = LotStatus.QUARANTINED
    if reason:
        # Rebuilt, not patched in place: see ``_meta_with_status_entry``.
        # ``meta.setdefault('quarantine', {})['reason'] = ...`` wrote through
        # to the dict the ORM had loaded, so a second quarantine with a new
        # reason compared equal to the old value and never left the process.
        meta = dict(lot.meta_data or {})
        meta['quarantine'] = {**meta.get('quarantine', {}), 'reason': reason}
        lot.meta_data = meta
    if reason or previous_status != lot.status:
        await _journal_status_async(
            db, lot, previous_status, reason=reason, user_id=user_id
        )
    await db.flush()
    return lot


async def release_lot_async(
    db: AsyncSession,
    organization_id: UUID,
    lot_id: UUID,
    *,
    user_id: UUID | None = None,
) -> StockLot | None:
    """Release a quarantined/held lot back to ACTIVE status.

    Journalled when the batch was held; releasing an active one changes
    nothing and writes nothing.
    """
    lot = await _locked_lot_async(db, organization_id, lot_id)
    if lot is None:
        return None
    previous_status = lot.status
    lot.status = LotStatus.ACTIVE
    if previous_status != lot.status:
        await _journal_status_async(
            db, lot, previous_status, reason=None, user_id=user_id
        )
    await db.flush()
    return lot


async def get_lot_detail_async(
    db: AsyncSession,
    organization_id: UUID,
    lot_id: UUID,
) -> StockLotDetailDTO | None:
    """One batch, with the product it belongs to and what is left of it.

    Two statements, not one: the shelves are a list and the lot is a row, and
    joining them would repeat every lot field per shelf. The quantity comes
    from the records (through ``stock_quants_from_records``), which is where
    the shelf is recorded — replaying the ledger would produce a second
    opinion, and the value of showing both is that a reader can see when they
    differ.
    """
    row = (
        await db.execute(
            select(StockLot, ProductTemplate.name, Uom.symbol)
            .outerjoin(
                ProductTemplate, ProductTemplate.id == StockLot.product_template_id
            )
            .outerjoin(Uom, Uom.id == ProductTemplate.uom_id)
            .where(
                StockLot.id == lot_id,
                StockLot.organization_id == organization_id,
            )
        )
    ).first()
    if row is None:
        return None
    lot, product_name, uom_symbol = row

    # The records' view: what each shelf holds of this batch and what of it
    # is promised, summed over the records and the reservation rows of the
    # group.
    quants = (
        await db.execute(
            select(
                stock_quants_from_records.c.storage_location_id,
                StorageLocation.name,
                func.sum(stock_quants_from_records.c.quantity),
                func.sum(stock_quants_from_records.c.reserved_quantity),
            )
            .outerjoin(
                StorageLocation,
                StorageLocation.id == stock_quants_from_records.c.storage_location_id,
            )
            .where(
                stock_quants_from_records.c.organization_id == organization_id,
                stock_quants_from_records.c.lot_id == lot_id,
                # A group drained to zero keeps its shelf, and a shelf that
                # once held the batch would answer "where is it" with a place
                # where none of it is — the same rule the stock list applies
                # (stock_quants_service), here instead keeping the
                # nothingLeft message reachable for a fully shipped lot.
                stock_quants_from_records.c.quantity != 0,
            )
            .group_by(
                stock_quants_from_records.c.storage_location_id, StorageLocation.name
            )
            .order_by(StorageLocation.name)
        )
    ).all()

    locations = [
        LotLocationDTO(
            location_id=location_id,
            location_name=location_name,
            quantity=quantity or Decimal('0'),
            reserved_quantity=reserved or Decimal('0'),
        )
        for location_id, location_name, quantity, reserved in quants
    ]

    detail = StockLotDetailDTO.model_validate(lot)
    detail.status = lot.effective_status
    detail.product_name = product_name
    detail.uom_symbol = uom_symbol
    detail.locations = locations
    detail.on_hand = sum((place.quantity for place in locations), start=Decimal('0'))
    detail.status_history = await _read_status_history_async(db, lot)
    return detail


async def _read_status_history_async(
    db: AsyncSession, lot: StockLot
) -> list[LotStatusEventDTO]:
    """The batch's decisions, newest first, with authors named.

    The trail section promises everything that happened to the batch, and a
    quarantine is a decision somebody made for a reason on a day — exactly
    what ``meta_data['status_history']`` records and the movement ledger
    never held. The author travels as a bare UUID in the entry; the names
    come back in one statement for the whole page of history, coalesced to
    the email the way the ledger names its authors. Entries written by code
    paths that append nothing (the module paths) simply are not here.
    """
    entries = (lot.meta_data or {}).get('status_history') or []
    entries = [entry for entry in entries if isinstance(entry, dict)]

    author_ids: set[UUID] = set()
    for entry in entries:
        raw = entry.get('by')
        if raw:
            try:
                author_ids.add(UUID(str(raw)))
            except ValueError:
                pass
    names: dict[UUID, str] = {}
    if author_ids:
        rows = await db.execute(
            select(
                User.id,
                func.coalesce(User.full_name, User.email).label('author_name'),
            ).where(User.id.in_(author_ids))
        )
        for user_id, author_name in rows:
            names[user_id] = author_name

    history: list[LotStatusEventDTO] = []
    for entry in reversed(entries):
        at = entry.get('at')
        try:
            moment = datetime.fromisoformat(str(at)) if at else None
        except ValueError:
            moment = None
        by = entry.get('by')
        history.append(
            LotStatusEventDTO(
                status=str(entry.get('status', '')),
                reason=entry.get('reason')
                if isinstance(entry.get('reason'), str)
                else None,
                at=moment,
                by_name=names.get(UUID(str(by))) if by else None,
            )
        )
    return history


async def list_lot_rows_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    product_template_id: UUID | None = None,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[StockLotDetailDTO], int]:
    """One page of batches, with the product they belong to and what is left.

    ``on_hand`` is summed from the records in the same statement — the list is
    read on a recall day, and "which batches exist" is a far less useful
    answer than "which batches are still out there". It reads the same view
    as the batch's own screen (``get_lot_detail_async``), so the two show one
    number.

    ``locations`` is left empty here: a page of two hundred batches would
    need two hundred breakdowns, and the batch's own screen already has it.
    """
    conditions = [StockLot.organization_id == organization_id]
    if product_template_id is not None:
        conditions.append(StockLot.product_template_id == product_template_id)
    if status is not None:
        # The date, not just the column: a status the page can show but not
        # narrow to is how "Expired" stayed an empty tab over a shelf of
        # month-old batches.
        conditions.append(effective_status_expression() == status)

    total = (
        await db.scalar(select(func.count()).select_from(StockLot).where(*conditions))
    ) or 0

    # Summed for the batches on the page only, each by its own product and
    # name. Summed for every batch of the organization and joined to the
    # page, it added up 300 000 records to print fifty batches.
    view = stock_quants_from_records
    on_hand = (
        select(func.sum(view.c.quantity))
        .where(
            view.c.organization_id == organization_id,
            view.c.product_template_id == StockLot.product_template_id,
            view.c.lot_id == StockLot.id,
        )
        .correlate(StockLot)
        .scalar_subquery()
    )

    stmt = (
        select(StockLot, ProductTemplate.name, Uom.symbol, on_hand)
        .outerjoin(ProductTemplate, ProductTemplate.id == StockLot.product_template_id)
        .outerjoin(Uom, Uom.id == ProductTemplate.uom_id)
        .where(*conditions)
        .order_by(StockLot.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    rows: list[StockLotDetailDTO] = []
    for lot, product_name, uom_symbol, quantity in (await db.execute(stmt)).all():
        detail = StockLotDetailDTO.model_validate(lot)
        detail.status = lot.effective_status
        detail.product_name = product_name
        detail.uom_symbol = uom_symbol
        detail.on_hand = quantity or Decimal('0')
        rows.append(detail)
    return rows, int(total)


def _meta_with_status_entry(
    meta_data: dict[str, Any] | None, entry: dict[str, Any]
) -> dict[str, Any]:
    """``meta_data`` with one more status entry, sharing nothing with the old.

    ``meta_data`` is a plain JSONB column, so SQLAlchemy notices a change by
    comparing the new value with the one it loaded. Appending to the list it
    loaded mutates both sides of that comparison at once: they stay equal, no
    UPDATE is emitted, and the write disappears without an error. The first
    reason a batch was ever given survived only because it started from NULL,
    and every one after it was lost.
    """
    old = meta_data or {}
    history = [*old.get('status_history', []), entry]
    return {**old, 'status_history': history}


async def set_lot_status_async(
    db: AsyncSession,
    organization_id: UUID,
    lot_id: UUID,
    status: str,
    reason: str | None = None,
    user_id: UUID | None = None,
) -> StockLot | None:
    """Put a batch into any of its states, keeping the reason it was given.

    The older ``quarantine_lot_async`` / ``release_lot_async`` pair covers
    two of the five states and is what the modules call. A person holding a
    supplier's recall notice needs the other three as well, and needs the
    notice itself recorded next to the status.

    The entry carries when and by whom as well as why. "Quarantined —
    supplier notice 41/26" answers the question somebody asks six months
    later; without a date and a name it only half answers it, and the two
    cost a line each.
    """
    lot = await _locked_lot_async(db, organization_id, lot_id)
    if lot is None:
        return None
    previous_status = lot.status
    lot.status = status
    if reason:
        lot.meta_data = _meta_with_status_entry(
            lot.meta_data,
            {
                'status': status,
                'reason': reason,
                'at': datetime.now(UTC).isoformat(),
                'by': str(user_id) if user_id else None,
            },
        )
    await _journal_status_async(
        db, lot, previous_status, reason=reason, user_id=user_id
    )
    await db.flush()
    return lot
