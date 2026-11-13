from __future__ import annotations

from datetime import date
from typing import Any, cast

from ._picking_fefo import expiry_of, is_open_pack
from .schemas import OpenedSuggestion


def check_opened_suggestion(
    scanned_item: Any,
    all_items: list[Any],
    template: Any,
) -> OpenedSuggestion | None:
    """
    Suggests switching to an already-opened pack if the scanned item is still sealed
    and another open pack exists. Returns None when suggestions would be noisy.

    Open means the mark opening writes (``is_open_pack``), the same answer the
    FEFO order and the candidates' ``opened`` flag give. A record without the
    mark used to be guessed open when it weighed less than the card's full
    pack, which took a smaller sealed bag for an open one.

    Accepts either ORM ``Item``/``ProductTemplate`` rows or ``ItemDTO``/
    ``ProductTemplateDTO`` (CoreAPI returns the DTO shape). Reads are
    duck-typed via ``getattr`` so the helper stays type-agnostic.
    """
    if is_open_pack(scanned_item):
        return None

    opened = [i for i in all_items if i.id != scanned_item.id and is_open_pack(i)]
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
