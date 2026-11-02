"""Total weight of a stock line, computed rather than stored.

The weight of one piece belongs to the product, not to each row in a
location: the same 500 g milk in three places does not have three different
unit weights. It lives on ``ProductTemplate.weight_value`` together with its
unit, and the weight of a line is simply quantity times that — see
ADR-015.

Storing the total on the item instead would need syncing on every quantity
change, which is the problem ADR-004 described for ``Item.quantity`` versus
the quant table it cached.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# UoM factors are relative to a category's reference unit (gram, millilitre),
# while a stored weight is expressed in kilograms or litres.
REFERENCE_UNITS_PER_STORED_UNIT = Decimal('1000')


#: Places a converted weight keeps: one gram of a kilogram, one millilitre
#: of a litre — the reference unit the conversion divides by. Dividing a
#: Decimal carries the full precision of the context, so an exact 1.6 kg was
#: serialised as "1.6000000000000" and the item card printed it verbatim,
#: claiming ten digits nobody weighed. The rounding belongs here, where the
#: conversion happens, and not on the column or in the screen that shows it.
STORED_UNIT_PLACES = 3

#: The UoM category counted in litres rather than kilograms.
VOLUME_UOM_CATEGORY = 'Volume'

#: UoM categories where the quantity is itself a weight or a volume.
CONTINUOUS_UOM_CATEGORIES = frozenset({'Weight', VOLUME_UOM_CATEGORY})


def quantity_as_weight(
    quantity: Decimal | float | None,
    uom_factor: float | None = None,
) -> Decimal | None:
    """Weight of a line counted in a weight or volume unit.

    There is no per-unit weight to look up in this case: 500 g *is* the
    weight. Only the unit conversion is left to do.
    """
    if quantity is None:
        return None

    factor = Decimal(str(uom_factor)) if uom_factor else Decimal('1')
    return _to_stored_unit(
        Decimal(str(quantity)) * factor / REFERENCE_UNITS_PER_STORED_UNIT
    )


def total_weight(
    quantity: Decimal | float | None,
    weight_value: Decimal | float | None,
    weight_uom_factor: float | None = None,
) -> Decimal | None:
    """Weight of a whole line, in kilograms (or litres for volume units).

    ``weight_value`` is the weight of a single unit as recorded on the
    product template, expressed in the UoM whose conversion ``factor`` is
    passed here. With no factor the value is read in the category's
    reference unit — grams.

    Returns ``None`` when the product has no unit weight, which is the
    normal case for items nobody weighed.
    """
    if not weight_value or quantity is None:
        return None

    factor = Decimal(str(weight_uom_factor)) if weight_uom_factor else Decimal('1')
    per_unit = Decimal(str(weight_value)) * factor / REFERENCE_UNITS_PER_STORED_UNIT
    return _to_stored_unit(Decimal(str(quantity)) * per_unit)


def _to_stored_unit(value: Decimal) -> Decimal:
    """Round a converted weight to the unit it was converted from."""
    return value.quantize(Decimal(10) ** -STORED_UNIT_PLACES, rounding=ROUND_HALF_UP)
