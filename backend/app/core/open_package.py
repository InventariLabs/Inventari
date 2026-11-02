"""Where a record keeps that it is an opened package.

Opening a package splits one unit off as a record of its own and writes the
time into that record's ``meta_data``. Several places have to read that
mark — the stock services that write it, and cooking, which prefers an open
pack to a sealed one — and the reading is the same everywhere, so it lives
here rather than in either of them.
"""

from __future__ import annotations

from datetime import date
from typing import Any

#: The namespaced key in ``meta_data``: other modules' keys sit beside it.
OPENED_KEY = 'opened'


def opened_at(meta_data: dict[str, Any] | None) -> str | None:
    """When the record was opened, as the ISO time it was written with."""
    opened = (meta_data or {}).get(OPENED_KEY)
    return opened.get('at') if isinstance(opened, dict) else None


def is_marked_open(meta_data: dict[str, Any] | None) -> bool:
    """Whether the record carries the mark of an opened package."""
    return opened_at(meta_data) is not None


#: The optional use-by date a person gives when opening a package. It sits in
#: the same namespace as the opening time, never over the batch's own date.
USE_BY_KEY = 'use_by'


def use_by_of(meta_data: dict[str, Any] | None) -> date | None:
    """The use-by date entered when the package was opened, if there is one."""
    opened = (meta_data or {}).get(OPENED_KEY)
    raw = opened.get(USE_BY_KEY) if isinstance(opened, dict) else None
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def effective_expiry(
    expiry_date: date | None, meta_data: dict[str, Any] | None
) -> date | None:
    """The day the goods stop being fit to use: the earlier of batch and use-by.

    Opening can only shorten a shelf life, so a use-by after the batch date
    changes nothing, and a record with neither date has none.
    """
    use_by = use_by_of(meta_data)
    if use_by is None:
        return expiry_date
    if expiry_date is None:
        return use_by
    return min(expiry_date, use_by)
