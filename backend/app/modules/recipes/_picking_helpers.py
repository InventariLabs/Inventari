from __future__ import annotations

from datetime import date
from typing import Any, cast

from ._picking_fefo import expiry_of, is_open_pack
from .schemas import OpenedSuggestion


def is_opened(item: Any, template: Any) -> bool:
    """Whether the record is an opened package.

    Opening writes a mark on the record, and that mark is the answer. A record
    that predates the mark is judged the way it always was: its quantity is
    below the full-pack weight on the card. That comparison is only
    meaningful when the item's UoM and the template's weight UoM are in the
    SAME category (e.g. both weight). Comparing pieces against grams flagged
    nearly every piece-counted item as "opened", so when the categories differ
    (or are unknown), the record is treated as NOT opened.
    """
    if is_open_pack(item):
        return True
    weight_value = getattr(template, 'weight_value', None) if template else None
    if not template or not weight_value:
        return False
    # Only compare within the same UoM category; otherwise skip (return False).
    item_uom_id = getattr(item, 'uom_id', None)
    tmpl_uom_id = getattr(template, 'weight_uom_id', None)
    if item_uom_id and tmpl_uom_id and item_uom_id != tmpl_uom_id:
        # Different UoMs: without an async conversion we cannot compare
        # meaningfully, so do not claim the item is opened.
        return False
    return float(item.quantity) < float(weight_value)


def check_opened_suggestion(
    scanned_item: Any,
    all_items: list[Any],
    template: Any,
) -> OpenedSuggestion | None:
    """
    Suggests switching to an already-opened pack if the scanned item is still sealed
    and another open pack exists. Returns None when suggestions would be noisy.

    Accepts either ORM ``Item``/``ProductTemplate`` rows or ``ItemDTO``/
    ``ProductTemplateDTO`` (CoreAPI returns the DTO shape). Reads are
    duck-typed via ``getattr`` so the helper stays type-agnostic.
    """
    if is_opened(scanned_item, template):
        return None

    opened = [
        i for i in all_items if i.id != scanned_item.id and is_opened(i, template)
    ]
    if not opened:
        return None

    opened.sort(key=lambda i: (expiry_of(i) is None, expiry_of(i) or date.max))
    best = opened[0]

    uom_symbol = _item_uom_symbol(best) or _template_uom_symbol(template)
    location_name = _location_name(best)

    return OpenedSuggestion(
        opened_item_id=best.id,
        opened_quantity=float(best.quantity),
        opened_uom=uom_symbol,
        opened_location=location_name,
        opened_expiry=str(expiry_of(best)) if expiry_of(best) else None,
    )


def _item_uom_symbol(item: Any) -> str | None:
    """The unit the record's own quantity is in, when the record says it."""
    symbol = getattr(item, 'uom_symbol', None)
    if not isinstance(symbol, str):
        symbol = getattr(getattr(item, 'uom', None), 'symbol', None)
    return symbol if isinstance(symbol, str) else None


def _template_uom_symbol(template: Any) -> str | None:
    weight_uom = getattr(template, 'weight_uom', None)
    if weight_uom is not None and getattr(weight_uom, 'symbol', None) is not None:
        return cast(str, weight_uom.symbol)
    return None


def _location_name(item: Any) -> str | None:
    """Return the storage location name for either an ORM row or an ItemDTO."""
    if hasattr(item, 'location_name') and item.location_name is not None:
        return cast(str | None, item.location_name)
    storage = getattr(item, 'storage_location', None)
    return cast(str | None, storage.name) if storage else None
