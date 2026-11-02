"""One precedence rule for a record's unit, and the paper it leaves.

The matched product template's unit is the reference: quantities named in
another unit are converted into it on the way in (the documents executor
does exactly that), and a BoM line in a unit that cannot be read as it is
refused with a named cause. A record may still be entered in a different
unit, but only through a choice the caller confirmed — and that choice is
written down, because a picker left on the previous product's grams turns
two kilograms into two grams without anybody deciding it.

This module owns both halves of that sentence: the refusal for a difference
nobody confirmed, and the history entry for one they did. A second copy of
either is how the rule drifts back into a per-door opinion.

A confirmed difference does not keep the record in the chosen unit. The
movement, the cost layer and the records' view carry a number and no unit,
so the number has to be the card's: the quantity and the unit price
are restated in the card's unit on the way in (``keep_in_card_unit_async``),
and the history entry keeps what was entered. That is the rule Odoo, ERPNext,
SAP and Dynamics keep: one stock unit per product, every entry converted
into it, nothing converted on the way out.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.money import quantise
from app.models.item import Item
from app.models.item_history import ItemAction
from app.models.product_template import ProductTemplate
from app.models.uom import Uom, UomCategory
from app.services.uom_service import STOCK_PLACES, convert_quantity, get_uom_async

from .history import log_history_async

#: The reason this module writes into a record's history. Spelled once, so
#: a reader searching for it finds every row that records the choice.
UNIT_CHOSEN_OVER_TEMPLATE = 'unit_chosen_over_template'

#: The category a piece is counted in. A pack, a can or a box each seed into
#: a category of their own, and only a piece is what the card's weight or
#: volume describes (ADR-015) — a pack holds a number of pieces nobody wrote.
PIECE_CATEGORY = 'Unit'

#: Decimals a record's unit price keeps (``items.purchase_price``).
PRICE_PLACES = 2


class _UnitWords:
    """The symbol and the name of one unit — how a record names it."""

    def __init__(self, symbol: str | None, name: str | None) -> None:
        self.symbol = symbol
        self.name = name


async def _unit_words_async(db: AsyncSession, uom_id: UUID | None) -> _UnitWords:
    """Read a unit's symbol and name, in the transaction that is already open.

    ``None``/``None`` for a blank unit — the same reading the update path
    uses when it names the old and the new unit beside each other.
    """
    if uom_id is None:
        return _UnitWords(None, None)
    row = (
        await db.execute(select(Uom.symbol, Uom.name).where(Uom.id == uom_id))
    ).first()
    if row is None:
        return _UnitWords(None, None)
    return _UnitWords(row[0], row[1])


async def refuse_unconfirmed_unit_difference_async(
    db: AsyncSession,
    *,
    template_uom_id: UUID | None,
    chosen_uom_id: UUID | None,
    product_name: str | None,
    confirmed: bool,
) -> None:
    """Refuse a unit the matched template does not keep, unless it is confirmed.

    Silence is the thing being refused, not the difference: a caller that
    knows the template says kilograms and types grams on purpose says so
    once, through ``unit_confirmed_over_template``, and the quantity is
    restated in kilograms with a history line behind it. Everything else — a filled-in field, a
    stale picker, a module answering for the wrong product — stops here,
    where both units can be named in the reader's language.

    A template with no unit of its own makes no claim, so there is nothing
    to differ from and nothing to confirm; the unitless-template case is the
    piece default's, decided elsewhere.
    """
    if confirmed or template_uom_id is None or chosen_uom_id is None:
        return
    if template_uom_id == chosen_uom_id:
        return

    template = await _unit_words_async(db, template_uom_id)
    chosen = await _unit_words_async(db, chosen_uom_id)
    raise ServiceRejectionError(
        'item_unit_differs_from_template_confirmation_required',
        product=product_name or '—',
        template_unit=template.symbol or '—',
        chosen_unit=chosen.symbol or '—',
    )


async def log_unit_chosen_over_template_async(
    db: AsyncSession,
    item: Item,
    action: ItemAction,
    *,
    template_uom_id: UUID | None,
    chosen_uom_id: UUID | None,
    entered_quantity: Decimal | None = None,
    user_id: UUID | None = None,
) -> None:
    """Write the confirmed choice into the record's history.

    The two units travel as symbols and as names, and the reason travels
    beside them: a later reader asking "the record says 0.5 kg, who typed
    500 g" finds a row that says so, in the same shape whatever door the
    choice came through. *entered_quantity* is the number as it was typed,
    in the chosen unit, and it sits beside the one the record keeps; an edit
    that named a unit and no quantity has none to write.

    A confirmation with no difference behind it is not a choice: callers
    that cannot know whether a difference exists — the importer spends the
    flag on every row — still pass it, so the flag alone cannot put an entry
    here. No difference, no row, like the refusal's own "no claim" reading.
    """
    if (
        template_uom_id is None
        or chosen_uom_id is None
        or template_uom_id == chosen_uom_id
    ):
        return
    template = await _unit_words_async(db, template_uom_id)
    chosen = await _unit_words_async(db, chosen_uom_id)
    changes: dict[str, Any] = {
        'reason': UNIT_CHOSEN_OVER_TEMPLATE,
        'template_uom': template.symbol,
        'template_uom_name': template.name,
        'chosen_uom': chosen.symbol,
        'chosen_uom_name': chosen.name,
    }
    if entered_quantity is not None:
        changes['entered_quantity'] = str(entered_quantity)
        changes['kept_quantity'] = str(item.quantity)
    await log_history_async(db, item, action, changes, user_id=user_id)


async def _is_piece_async(db: AsyncSession, uom: Uom) -> bool:
    name = await db.scalar(
        select(UomCategory.name).where(UomCategory.id == uom.category_id)
    )
    return name == PIECE_CATEGORY


async def _card_units_per_chosen_unit_async(
    db: AsyncSession, card: ProductTemplate, card_uom: Uom, chosen: Uom
) -> Decimal | None:
    """How many of the card's units one chosen unit is, or ``None``.

    Within a category it is the units' own ratio — a gram is 0.001 kg.
    Between a piece and a weight or a volume it is what one piece measures,
    which the card keeps: three loaves on a card kept in kilograms weigh
    three times the card's loaf, and a kilo of apples on a card that counts
    them is a kilo over the card's apple. Nothing else crosses a category.
    """
    ratio, ok = convert_quantity(Decimal('1'), chosen, card_uom)
    if ok:
        return ratio or None
    chosen_is_piece = await _is_piece_async(db, chosen)
    if chosen_is_piece == await _is_piece_async(db, card_uom):
        return None
    for value, measure_uom_id in (
        (card.weight_value, card.weight_uom_id),
        (card.volume_value, card.volume_uom_id),
    ):
        measure = await get_uom_async(db, measure_uom_id) if measure_uom_id else None
        if not value or measure is None:
            continue
        one_piece = Decimal(str(value))
        if chosen_is_piece:
            per_piece, ok = convert_quantity(one_piece, measure, card_uom)
            if ok and per_piece:
                return per_piece
        else:
            per_piece, ok = convert_quantity(one_piece, measure, chosen)
            if ok and per_piece:
                return Decimal('1') / per_piece
    return None


async def keep_in_card_unit_async(
    db: AsyncSession,
    data: dict[str, Any],
    card: ProductTemplate | None,
    *,
    product_name: str | None,
) -> None:
    """Restate *data*'s quantity and unit price in the card's unit, in place.

    *data* is a record's incoming fields — a create's or an edit's — with
    the unit already settled and its difference from the card already
    confirmed. When the unit is not the card's, the quantity is converted
    into the card's unit, rounded to the three places every stock column
    keeps, the unit price is converted the other way so the value stays
    what it was, and the unit becomes the card's. A card with no unit makes
    no claim, and a record without a card has no stock to keep.

    A unit that does not convert is refused by name, both units in the
    reader's language, before anything is written: a number the stock
    cannot read is not one to keep beside it.
    """
    chosen_uom_id = data.get('uom_id')
    if (
        card is None
        or card.uom_id is None
        or chosen_uom_id is None
        or chosen_uom_id == card.uom_id
    ):
        return
    card_uom = await get_uom_async(db, card.uom_id)
    chosen = await get_uom_async(db, chosen_uom_id)
    ratio = (
        await _card_units_per_chosen_unit_async(db, card, card_uom, chosen)
        if card_uom is not None and chosen is not None
        else None
    )
    if ratio is None:
        raise ServiceRejectionError(
            'item_unit_not_convertible_to_card',
            product=product_name or '—',
            template_unit=card_uom.symbol if card_uom else '—',
            chosen_unit=chosen.symbol if chosen else '—',
        )
    if data.get('quantity') is not None:
        data['quantity'] = quantise(
            Decimal(str(data['quantity'])) * ratio, STOCK_PLACES
        )
    if data.get('purchase_price') is not None:
        data['purchase_price'] = quantise(
            Decimal(str(data['purchase_price'])) / ratio, PRICE_PLACES
        )
    data['uom_id'] = card.uom_id


__all__ = [
    'UNIT_CHOSEN_OVER_TEMPLATE',
    'keep_in_card_unit_async',
    'log_unit_chosen_over_template_async',
    'refuse_unconfirmed_unit_difference_async',
]
