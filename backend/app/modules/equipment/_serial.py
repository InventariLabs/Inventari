"""Where an asset's serial number lives, and how to read it.

An asset is identified by its serial number, and the application used to
write it in two places depending on which door the asset came through: the
batch path filled the core ``Item.serial_number`` column, while the single
form and the import wrote only ``meta_data['equipment']['serial_number']``.
Two assets created two ways therefore carried their number in two different
places, and the core search — which the command palette asks — could see
neither.

The column is now the one place every write path fills. It is a system
column the core already owns, it is indexable, and core search can reach it
without knowing this module exists. The namespace is read here as a
fallback so rows written before the consolidation keep showing their number
even where the data migration has not run yet.
"""

from typing import Any


def serial_of(item: Any) -> str | None:
    """Serial number of *item*, column first, legacy namespace second."""
    column = getattr(item, 'serial_number', None)
    if column:
        return str(column)
    return serial_from_meta(getattr(item, 'meta_data', None))


def serial_from_meta(meta: dict[str, Any] | None) -> str | None:
    """Serial number carried by a metadata mapping, or None."""
    namespace = (meta or {}).get('equipment') or {}
    value = namespace.get('serial_number')
    return str(value) if value else None


def without_serial(equipment_meta: dict[str, Any]) -> dict[str, Any]:
    """The equipment namespace with the serial number taken out.

    Write paths call this before persisting: the number goes to the column,
    and leaving a copy behind would let the two drift apart on the next edit.
    """
    return {k: v for k, v in equipment_meta.items() if k != 'serial_number'}
