from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from app.core.open_package import effective_expiry, is_marked_open

from .models import RecipeIngredient

FEFO_URGENCY_THRESHOLD_DAYS = 30

_SPICE_UOMS = {'g', 'ml', 'mg'}
_SPICE_THRESHOLD = 10.0


class StockedItem(Protocol):
    """What FEFO ordering reads off an item.

    Both an ORM ``Item`` and an ``ItemDTO`` satisfy this, which is the
    point: availability reads go through CoreAPI and come back as DTOs,
    while picking still holds ORM rows, and the ordering is the same either
    way.
    """

    @property
    def expiry_date(self) -> date | None: ...

    @property
    def quantity(self) -> Decimal | None: ...


def expiry_of(item: object) -> date | None:
    """The day cooking judges the record by: its batch date or, if earlier, the
    use-by given when it was opened."""
    meta_data: Any = getattr(item, 'meta_data', None)
    return effective_expiry(getattr(item, 'expiry_date', None), meta_data)


def is_open_pack(item: object) -> bool:
    """Whether the record is an opened package, by the mark opening writes."""
    meta_data: Any = getattr(item, 'meta_data', None)
    return is_marked_open(meta_data)


def is_past(item: StockedItem, today: date) -> bool:
    """Past its date — the core's rule: the date itself is still good.

    ``services/items/expiry.py`` holds the same rule for the counts; *today*
    is the organization's day, as it is there.
    """
    return (expiry := expiry_of(item)) is not None and expiry < today


def _fefo_sort_key(
    item: StockedItem, today: date
) -> tuple[bool, bool, date, bool, Decimal | int]:
    # First expiring, first out — among the goods still fit to use. Stock
    # past its date used to lead the order, having the earliest date of all,
    # so the chicken that went off on Monday was the pick while a fresh pack
    # sat beside it. It goes last now: still listed, never first.
    #
    # On the same date an opened pack goes first: it keeps worse than a
    # sealed one, and the sealed bag beside it stays sealed. Then the larger
    # quantity, so same-expiry items resolve deterministically (unified with
    # _helpers._fefo_sort).
    return (
        is_past(item, today),
        expiry_of(item) is None,
        expiry_of(item) or date.max,
        not is_open_pack(item),
        -(item.quantity or 0),
    )


def fefo_order[T: StockedItem](items: Iterable[T], today: date) -> list[T]:
    """Culinary FEFO: fit goods first, then expiry, then open before sealed, then quantity.

    This is a cooking suggestion, not the Core's removal strategy. Core
    resolves configured FIFO/FEFO for stock posting; cooking keeps expired
    goods visible but behind fit goods, and prefers the open pack, then the
    larger one, when expiry ties. Availability and picking share this ordering.
    """
    return sorted(items, key=lambda item: _fefo_sort_key(item, today))


def fefo_days_left(sorted_items: Sequence[StockedItem], today: date) -> int | None:
    """Days left on the first pick, when it is urgent and a later one exists.

    ``None`` for a first pick already past its date: the number went
    negative and the screen said "Short shelf life" beside a date gone by.
    What is past its date is not short of shelf life — it has none.
    """
    if len(sorted_items) < 2:
        return None
    best, second = sorted_items[0], sorted_items[1]
    best_expiry = expiry_of(best)
    if best_expiry is None or is_past(best, today):
        return None
    days_left = (best_expiry - today).days
    if days_left > FEFO_URGENCY_THRESHOLD_DAYS:
        return None
    second_expiry = expiry_of(second)
    if second_expiry and second_expiry > best_expiry:
        return days_left
    return None


def select_best_item[T: StockedItem](
    items: list[T], *, today: date
) -> tuple[T, int | None]:
    """FEFO-based best item selection. Returns (item, fefo_days_left | None)."""
    if not items:
        raise RuntimeError('No items to select from')

    sorted_items = fefo_order(items, today)
    return sorted_items[0], fefo_days_left(sorted_items, today)


def open_pack_meets_earlier_sealed(items: Sequence[StockedItem], today: date) -> bool:
    """An open pack and a sealed one that expires before it are both on hand.

    Which of the two the cook should use is the cook's call: the open pack
    will not keep, the sealed one will not wait. On the same date there is no
    question, the open pack goes first. A sealed pack already past its date is
    not a rival to anything.
    """
    open_dates = [expiry_of(i) for i in items if is_open_pack(i)]
    sealed_dates = [
        day
        for i in items
        if not is_open_pack(i)
        and (day := expiry_of(i)) is not None
        and not is_past(i, today)
    ]
    return any(
        opened is None or earliest < opened
        for opened in open_dates
        for earliest in sealed_dates
    )


class LocatedItem(Protocol):
    @property
    def location_id(self) -> UUID | None: ...


def needs_disambiguation(items: Sequence[LocatedItem]) -> bool:
    """Disambiguation is needed only when items span multiple physical locations."""
    locations = {i.location_id for i in items}
    return len(locations) > 1


def _resolve_user_id(user: object) -> UUID:
    if isinstance(user, UUID):
        return user
    user_id = getattr(user, 'id', None)
    if isinstance(user_id, UUID):
        return user_id
    raise RuntimeError('User id is required for picking quantity updates')


def _should_auto_skip(ingredient: RecipeIngredient, scaled_qty: float) -> bool:
    """Returns True when the ingredient should be pre-skipped in the picking session.

    Priority:
    1. Explicit override: ingredient.picking_skip is True/False
    2. is_optional flag
    3. Heuristic: UOM is g/ml/mg and scaled qty <= 10

    Pieces are never folded away by their amount: one egg or one onion is a
    main ingredient, not a seasoning, and the fold-out it used to land in
    says "Spices & small quantities". The recipe card draws the same line —
    only weight and volume amounts read as seasoning — so a piece the cook
    means as a spice is skipped through ``picking_skip``.
    """
    if ingredient.picking_skip is True:
        return True
    if ingredient.picking_skip is False:
        return False
    if ingredient.is_optional:
        return True
    uom_symbol = ingredient.uom.symbol.lower() if ingredient.uom else ''
    if uom_symbol in _SPICE_UOMS and scaled_qty <= _SPICE_THRESHOLD:
        return True
    return False
