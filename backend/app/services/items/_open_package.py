"""Use a package partially: open one unit as a record of its own.

A bag of flour on a shelf is one record of three bags. Once somebody opens
one, that bag is a different thing from the two beside it — it has a date it
was opened, it will be used up first, and what is left of it is a fraction of
a piece. Putting that on the record that holds all three would make every
quantity ambiguous, so the opened unit is split off as a record of its own
(the same split a partial transfer makes), the opening time goes into its
``meta_data`` and its history, and the amount used is an ordinary USED
movement.

The remainder stays in the card's unit: the stock view and the ledger sum
quantities without a unit, so 1.5 kg left of a 2 kg bag is 0.75 of a piece.
The person says what is LEFT, in the weight or volume they see on the bag —
that cannot take the amount off twice when the button is pressed twice, and
it is what looking at the bag tells them.

Everything runs under the record's stock lock, in the caller's transaction.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType, UserContextDTO
from app.core.exceptions import ServiceRejectionError
from app.core.money import quantise
from app.core.open_package import OPENED_KEY, USE_BY_KEY, opened_at, use_by_of
from app.models.item import Item
from app.models.item_history import ItemAction
from app.models.product_template import ProductTemplate
from app.models.uom import UomCategory
from app.schemas.item import ItemConsumeRequest, ItemCreate
from app.services.audit_service import log_action_async
from app.services.uom_service import STOCK_PLACES, get_uom_async

from ._stock_quant import apply_quantity_change_async, lock_record_stock_async
from ._unit_choice import PIECE_CATEGORY, _card_units_per_chosen_unit_async
from .history import log_history_async

#: Categories a product is counted in. A piece is what the card's weight or
#: volume describes; a pack, can, bottle, box or bag holds a number of pieces
#: nobody wrote down, so it can be opened and finished but not measured.
_COUNTED_CATEGORIES = frozenset({PIECE_CATEGORY, 'Pack', 'Can', 'Bottle', 'Box', 'Bag'})


def is_open(item: Item) -> bool:
    """Whether the record is an opened package.

    A record that predates the mark and holds a fraction of a piece is read
    the same way: it can only be what is left of one.
    """
    if opened_at(item.meta_data) is not None:
        return True
    return item.quantity is not None and Decimal('0') < item.quantity < Decimal('1')


def _with_opening(meta_data: dict[str, Any] | None, when: datetime) -> dict[str, Any]:
    merged = dict(meta_data or {})
    opened = dict(merged.get(OPENED_KEY) or {})
    opened.setdefault('at', when.isoformat())
    merged[OPENED_KEY] = opened
    return merged


async def _category_name_async(db: AsyncSession, category_id: UUID) -> str | None:
    return await db.scalar(
        select(UomCategory.name).where(UomCategory.id == category_id)
    )


async def _split_one_unit_async(
    db: AsyncSession, item: Item, user: UserContextDTO, when: datetime
) -> Item:
    """Take one unit out of a record that holds several, as a record of its own.

    The stock on the shelf does not change — a unit moves from one record to
    another beside it — so neither the ledger nor the cost layers are
    written. The new record is the same goods: card, batch, owner, expiry,
    price and the date it was received all ride along. The identity fields
    (barcode, serial number) name the record, not the stock in it, and stay
    where they were.
    """
    from ._create import create_item_async

    await apply_quantity_change_async(
        db,
        item,
        item.quantity - Decimal('1'),
        old_quantity=item.quantity,
        post_the_change=False,
        user_id=user.id,
    )
    return await create_item_async(
        db,
        ItemCreate(
            name=item.name,
            template_id=item.template_id,
            category_id=item.category_id,
            location_id=item.storage_location_id,
            quantity=Decimal('1'),
            uom_id=item.uom_id,
            brand=item.brand,
            expiry_date=item.expiry_date,
            shelf_location=item.shelf_location,
            metadata=_with_opening(item.meta_data, when),
            purchase_price=item.purchase_price,
            currency=item.currency,
            image_url=item.image_url,
            added_date=item.added_date,
        ),
        user,
        post_the_change=False,
        lot_id=item.lot_id,
        owner_id=item.owner_id,
    )


async def _pieces_left_async(
    db: AsyncSession,
    item: Item,
    card: ProductTemplate | None,
    left: Decimal,
    left_uom_id: UUID | None,
) -> Decimal:
    """What is left, restated in the card's unit (pieces).

    No unit named means the quantity is already in the card's — 0.75 of a
    piece. A weight or volume converts through what one piece measures, the
    way every other door restates an entry in the card's unit.
    """
    if left_uom_id is None or left_uom_id == item.uom_id:
        return quantise(left, STOCK_PLACES)
    card_uom = await get_uom_async(db, item.uom_id) if item.uom_id else None
    chosen = await get_uom_async(db, left_uom_id)
    ratio = (
        await _card_units_per_chosen_unit_async(db, card, card_uom, chosen)
        if card is not None and card_uom is not None and chosen is not None
        else None
    )
    if ratio is None:
        raise ServiceRejectionError(
            'item_unit_not_convertible_to_card',
            product=item.name,
            template_unit=card_uom.symbol if card_uom else '—',
            chosen_unit=chosen.symbol if chosen else '—',
        )
    return quantise(left * ratio, STOCK_PLACES)


async def use_partially_async(
    db: AsyncSession,
    item: Item,
    user: UserContextDTO,
    *,
    left: Decimal | None,
    left_uom_id: UUID | None = None,
    use_by: date | None = None,
    set_use_by: bool = False,
) -> Item:
    """Open a package, or record how much of an open one is left.

    ``left`` is what remains of the package — in the unit named by
    ``left_uom_id``, or in the card's own when none is named. ``None`` only
    marks the package as opened and changes no quantity; zero says it is
    finished. Returns the record that is now the open package.

    Saying the same ``left`` twice takes nothing off the second time: the
    record already holds that much.

    ``set_use_by`` says a use-by date was given (``use_by`` may then be
    ``None`` to clear it); the date is kept beside the opening time and never
    replaces the batch's own.
    """
    from .move_service import consume_item

    await lock_record_stock_async(db, item)

    if item.serial_number:
        raise ServiceRejectionError(
            'use_partially_serialized', serial_number=item.serial_number
        )
    uom = await get_uom_async(db, item.uom_id) if item.uom_id else None
    category_name = await _category_name_async(db, uom.category_id) if uom else None
    if category_name not in _COUNTED_CATEGORIES:
        raise ServiceRejectionError(
            'use_partially_needs_counted_unit', item_name=item.name
        )
    if left is not None and left > 0 and category_name != PIECE_CATEGORY:
        raise ServiceRejectionError(
            'use_partially_pack_has_no_measure', item_name=item.name
        )

    chosen_unit = await get_uom_async(db, left_uom_id) if left_uom_id else None
    left_unit = chosen_unit.symbol if chosen_unit else None
    when = datetime.now(UTC)
    already_open = is_open(item)
    marked = opened_at(item.meta_data) is not None

    # "Opened" with nothing said about the amount: the flag and the time, and
    # the quantity as it was.
    if left is None and already_open:
        if set_use_by:
            await _apply_use_by_async(db, item, user, use_by)
        return item

    remainder = Decimal('0')
    if left is not None and left > 0:
        card = (
            await db.get(ProductTemplate, item.template_id)
            if item.template_id
            else None
        )
        remainder = await _pieces_left_async(db, item, card, left, left_uom_id)
    available = item.quantity if already_open else Decimal('1')
    if remainder > available:
        raise ServiceRejectionError(
            'use_partially_more_than_left',
            item_name=item.name,
            available=format(available.normalize(), 'f'),
            requested=format(remainder.normalize(), 'f'),
        )

    # One unit of several is split off; a record that is the one unit (or the
    # open remainder already) is the package itself.
    if already_open or item.quantity == 1:
        target = item
        if not marked:
            target.meta_data = _with_opening(item.meta_data, when)
            await _log_opened(db, target, item, user, left=left, left_unit=left_unit)
    else:
        before = item.quantity
        target = await _split_one_unit_async(db, item, user, when)
        # The record the person scanned lost a unit: say so on its own
        # history, as the other half of the note the new record carries.
        await log_history_async(
            db,
            item,
            ItemAction.QUANTITY_CHANGED,
            {'old': str(before), 'new': str(item.quantity)},
            user_id=user.id,
        )
        await _log_opened(db, target, item, user, left=left, left_unit=left_unit)

    if set_use_by:
        await _apply_use_by_async(db, target, user, use_by)
    used = available - remainder if left is not None else Decimal('0')
    if used > 0:
        await consume_item(
            db, target, ItemConsumeRequest(quantity=used, reason=None), user
        )
    return target


async def _log_opened(
    db: AsyncSession,
    target: Item,
    source: Item,
    user: UserContextDTO,
    *,
    left: Decimal | None,
    left_unit: str | None = None,
) -> None:
    details: dict[str, Any] = {'opened_at': opened_at(target.meta_data)}
    if target.id != source.id:
        details['split_from'] = str(source.id)
    if left is not None:
        details['left'] = float(left)
        if left_unit:
            details['left_unit'] = left_unit
    await db.flush()
    await log_history_async(db, target, ItemAction.OPENED, details, user_id=user.id)


async def open_to_take_part_async(
    db: AsyncSession, item: Item, user: UserContextDTO
) -> Item:
    """The record a part of a package is taken from, opened if it was sealed.

    Cooking takes 200 g from a 2 kg bag: that bag is open from then on, and
    the bag beside it is not. The same opening Use partially makes, without
    saying how much is left — the amount taken is the movement that follows.
    A record that is already open, kept in a measured unit or carrying a
    serial number is not a package to open and comes back as it was.
    """
    if item.serial_number or is_open(item):
        return item
    uom = await get_uom_async(db, item.uom_id) if item.uom_id else None
    category_name = await _category_name_async(db, uom.category_id) if uom else None
    if category_name not in _COUNTED_CATEGORIES:
        return item
    return await use_partially_async(db, item, user, left=None)


async def _apply_use_by_async(
    db: AsyncSession, item: Item, user: UserContextDTO, use_by: date | None
) -> None:
    """Write (or clear) the use-by beside the opening time and say so."""
    before = use_by_of(item.meta_data)
    if before == use_by:
        return
    merged = dict(item.meta_data or {})
    opened = dict(merged.get(OPENED_KEY) or {})
    if use_by is None:
        opened.pop(USE_BY_KEY, None)
    else:
        opened[USE_BY_KEY] = use_by.isoformat()
    merged[OPENED_KEY] = opened
    item.meta_data = merged
    await db.flush()
    await log_history_async(
        db,
        item,
        ItemAction.UPDATED,
        {
            USE_BY_KEY: {
                'old': before.isoformat() if before else None,
                'new': use_by.isoformat() if use_by else None,
            }
        },
        user_id=user.id,
    )
    await log_action_async(
        db,
        organization_id=item.organization_id,
        user_id=user.id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.ITEM,
        target_id=item.id,
        snapshot={
            'name': item.name,
            'before': {USE_BY_KEY: before.isoformat() if before else None},
            'after': {USE_BY_KEY: use_by.isoformat() if use_by else None},
        },
    )


async def set_use_by_async(
    db: AsyncSession, item: Item, user: UserContextDTO, use_by: date | None
) -> Item:
    """Edit, or with ``None`` clear, the use-by of an opened package.

    A sealed package has no use-by to give: it is judged by the batch's date
    until somebody opens it.
    """
    await lock_record_stock_async(db, item)
    if opened_at(item.meta_data) is None:
        raise ServiceRejectionError('use_by_needs_open_package', item_name=item.name)
    await _apply_use_by_async(db, item, user, use_by)
    return item
