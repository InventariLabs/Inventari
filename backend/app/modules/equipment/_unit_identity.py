"""What tells two units of the same model apart.

A fleet is ten models and sixty units. Naming a row by its model alone —
"PowerEdge R650", four times in a row — asks the reader to collect one of
four identical things. The serial and the asset tag are what the label on
the case says, and the asset list has shown them in one column for as long
as it has existed; the dashboard just never asked for them.

A leaf module on purpose: the assignment service and the overdue service
both need this, and the latter stays clear of the former to avoid a circular
import during app startup.
"""

from __future__ import annotations

from typing import Any


def unit_identifiers(item: Any) -> tuple[str | None, str | None]:
    """Return ``(serial_number, asset_tag)`` for an item row, or ``(None, None)``.

    The serial lives in the core column — the one place every write path
    fills. The module namespace is read after it, for rows written before
    that was true, which is the same order the asset table reads them in.
    """
    if item is None:
        return None, None
    namespace = (getattr(item, 'meta_data', None) or {}).get('equipment', {})
    serial = getattr(item, 'serial_number', None) or namespace.get('serial_number')
    return serial or None, namespace.get('asset_tag') or None


def audit_identity(item: Any) -> dict[str, Any]:
    """How an asset is named in the organization log: name **and** serial.

    ``target_id`` alone sends the reader back into the app to find out which
    laptop the row is about, and a name alone is worse than that on a fleet —
    "ThinkPad T14" four times over is a row you cannot act on. The serial is
    what the label on the case says.
    """
    serial, _asset_tag = unit_identifiers(item)
    return {'name': getattr(item, 'name', None), 'serial_number': serial}
