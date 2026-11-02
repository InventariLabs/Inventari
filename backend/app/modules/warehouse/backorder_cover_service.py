"""Whether the stock a backorder draft waits for is on the shelves now.

A short dispatch leaves a draft for the rest, and To do lists it as a decision.
Whether the draft can be filled is not stored anywhere: it is the draft's lines
against what the issuing shelves hold at the moment of reading, so it follows
the stock however the stock rose — a receipt, a correction, a count, a
transfer — without any of those routes having to know a draft exists.

Stock counts the way the dispatch would draw it (``plan_draw_async``: free of
other documents' holds, in a batch that may be used), under the draft's source
zone when it names one. Two shelves are left out because nothing is issued
from them: a receiving area, where goods wait to be put away, and the
quarantine shelf, where a receipt holds what it could not release.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from . import document_types as dt
from ._receiving_area import list_receiving_modes_async
from ._stock_executor_helpers import _resolve_lot
from .document_profile_service import get_profile
from .models import Document

StockCover = Literal['full', 'partial', 'none']

_ZERO = Decimal('0')

#: What a draw is asked for: the product, the shelves it may come from (``None``
#: for every shelf) and the batch the line names, if any.
_FreeKey = tuple[UUID, tuple[UUID, ...] | None, UUID | None]


async def _not_issued_from_async(db: AsyncSession, org_id: UUID) -> set[UUID]:
    """The receiving areas and the quarantine shelf, with everything under them."""
    roots = [
        row.receiving_location_id
        for row in await list_receiving_modes_async(db, org_id)
        if row.receiving_location_id is not None
    ]
    profile = await get_profile(db, org_id)
    if profile is not None and profile.quarantine_location_id is not None:
        roots.append(profile.quarantine_location_id)
    shelves = set(roots)
    for root in roots:
        shelves.update(await core_api.locations.descendant_ids_async(db, org_id, root))
    return shelves


async def backorder_cover_async(
    db: AsyncSession, org_id: UUID, drafts: list[Document]
) -> dict[UUID, StockCover]:
    """For each draft that takes goods out, how much of it the shelves cover now.

    ``full`` when every line is covered, ``none`` when no line is at all and
    ``partial`` between. Lines of one product share what is free, so a draft
    cannot count the same units twice. A draft that brings goods in has no
    cover to report and is left out.
    """
    outbound = [
        draft
        for draft in drafts
        if dt.is_dispatch(draft.type) or dt.is_transfer(draft.type)
    ]
    if not outbound:
        return {}
    excluded = await _not_issued_from_async(db, org_id)
    zones: dict[UUID, tuple[UUID, ...]] = {}
    free: dict[_FreeKey, Decimal] = {}
    covers: dict[UUID, StockCover] = {}
    for draft in outbound:
        shelves: tuple[UUID, ...] | None = None
        if draft.source_location_id is not None:
            if draft.source_location_id not in zones:
                zones[draft.source_location_id] = (
                    draft.source_location_id,
                    *await core_api.locations.descendant_ids_async(
                        db, org_id, draft.source_location_id
                    ),
                )
            shelves = zones[draft.source_location_id]
        left: dict[_FreeKey, Decimal] = {}
        wanted = covered = _ZERO
        for line in draft.lines:
            # A line may name only the record it takes from; the record's
            # card is the product then, as everywhere a line is read.
            template_id = line.product_template_id or (
                line.item.template_id if line.item is not None else None
            )
            needed = line.expected_quantity - (line.done_quantity or _ZERO)
            if template_id is None or needed <= 0:
                continue
            lot_id = await _resolve_lot(db, draft, line, create_if_missing=False)
            named_lot = bool(line.serial_number or line.batch_number)
            key: _FreeKey = (template_id, shelves, lot_id)
            if key not in free:
                free[key] = (
                    _ZERO
                    if named_lot and lot_id is None
                    else sum(
                        (
                            draw.consumed
                            for draw in await core_api.stock.plan_draw_async(
                                db,
                                org_id,
                                template_id,
                                None,
                                None,
                                any_owner=True,
                                lot_id=lot_id,
                                among_shelves=shelves,
                            )
                            if draw.location_id not in excluded
                        ),
                        _ZERO,
                    )
                )
            try:
                needed = await core_api.uoms.to_stock_uom_async(
                    db, org_id, template_id, needed, line.uom_id
                )
            except ValueError:
                # Units that do not convert cannot be compared: nothing is
                # promised for this line.
                wanted += 1
                continue
            available = left.setdefault(key, free[key])
            taken = min(needed, available)
            left[key] = available - taken
            wanted += needed
            covered += taken
        if wanted > 0:
            covers[draft.id] = (
                'full' if covered >= wanted else 'partial' if covered > 0 else 'none'
            )
    return covers
