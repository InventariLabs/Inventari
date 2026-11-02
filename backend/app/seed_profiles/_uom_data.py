"""Unit-of-measure seed data — one catalogue, for every path that seeds it.

Pure data, no DB access. :func:`app.seed_profiles.base.seed_uom` persists it
and :mod:`app._seed_uom` delegates there, so an installation gets the same
units whether it was built by ``seed_data`` or by applying a product profile.

They used to be two lists that had drifted: twenty units here, sixteen there,
and ``rounding`` only on one side — so a workspace built from a profile could
record a quantity of 1.5 pieces, because the column default is 0.01 and
nothing had said otherwise.

``factor`` is relative to the category's reference unit, and the reference is
the one whose factor is 1. Factors and roundings are written as ``Decimal``:
the columns are exact, and a float literal here would only describe the
catalogue wrongly — SQLAlchemy converted it on the way in, but a reader saw
``28.3495`` and had to know that a double cannot hold it. Length is stated in centimetres for that reason:
the flag used to sit on Meter while the scale was centimetre-based, which
converts correctly — every conversion is a ratio — but describes the
catalogue wrongly to anyone reading it.
"""

from decimal import Decimal
from typing import Any

UOM_CATEGORIES: list[dict[str, str]] = [
    {'name': 'Weight'},
    {'name': 'Volume'},
    {'name': 'Unit'},
    {'name': 'Length'},
    # Bulk packaging lives one unit per category: a pack is not a
    # share of the piece's dimension, and no unit table knows the ratio of
    # packaging to contents — that belongs to the product. Their
    # own categories are what makes every conversion path refuse pack↔pcs
    # instead of quietly equating both at factor 1.0.
    {'name': 'Pack'},
    {'name': 'Can'},
    {'name': 'Bottle'},
    {'name': 'Box'},
    {'name': 'Bag'},
]

UOM_UNITS: list[dict[str, Any]] = [
    # Weight — reference: gram
    {
        'category': 'Weight',
        'name': 'Gram',
        'symbol': 'g',
        'factor': Decimal('1.0'),
        'is_reference': True,
        'rounding': Decimal('0.001'),
    },
    {
        'category': 'Weight',
        'name': 'Kilogram',
        'symbol': 'kg',
        'factor': Decimal('1000.0'),
        'is_reference': False,
        'rounding': Decimal('0.001'),
    },
    {
        'category': 'Weight',
        'name': 'Milligram',
        'symbol': 'mg',
        'factor': Decimal('0.001'),
        'is_reference': False,
        'rounding': Decimal('0.001'),
    },
    {
        'category': 'Weight',
        'name': 'Ounce',
        'symbol': 'oz',
        'factor': Decimal('28.3495'),
        'is_reference': False,
        'rounding': Decimal('0.001'),
    },
    {
        'category': 'Weight',
        'name': 'Pound',
        'symbol': 'lb',
        'factor': Decimal('453.592'),
        'is_reference': False,
        'rounding': Decimal('0.001'),
    },
    # Volume — reference: millilitre
    {
        'category': 'Volume',
        'name': 'Milliliter',
        'symbol': 'ml',
        'factor': Decimal('1.0'),
        'is_reference': True,
        'rounding': Decimal('0.001'),
    },
    {
        'category': 'Volume',
        'name': 'Liter',
        'symbol': 'l',
        'factor': Decimal('1000.0'),
        'is_reference': False,
        'rounding': Decimal('0.001'),
    },
    # Unit — counted, never divided: rounding 1.0 across the category.
    # Piece is the whole category: bulk packaging (pack/can/bottle/box/bag)
    # moved to its own single-unit categories below.
    {
        'category': 'Unit',
        'name': 'Piece',
        'symbol': 'pcs',
        'factor': Decimal('1.0'),
        'is_reference': True,
        'rounding': Decimal('1.0'),
    },
    # Bulk packaging — each unit is the reference of its own category, so it
    # labels a quantity without converting into pieces.
    {
        'category': 'Pack',
        'name': 'Pack',
        'symbol': 'pack',
        'factor': Decimal('1.0'),
        'is_reference': True,
        'rounding': Decimal('1.0'),
    },
    {
        'category': 'Can',
        'name': 'Can',
        'symbol': 'can',
        'factor': Decimal('1.0'),
        'is_reference': True,
        'rounding': Decimal('1.0'),
    },
    {
        'category': 'Bottle',
        'name': 'Bottle',
        'symbol': 'bottle',
        'factor': Decimal('1.0'),
        'is_reference': True,
        'rounding': Decimal('1.0'),
    },
    {
        'category': 'Box',
        'name': 'Box',
        'symbol': 'box',
        'factor': Decimal('1.0'),
        'is_reference': True,
        'rounding': Decimal('1.0'),
    },
    {
        'category': 'Bag',
        'name': 'Bag',
        'symbol': 'bag',
        'factor': Decimal('1.0'),
        'is_reference': True,
        'rounding': Decimal('1.0'),
    },
    # Length — reference: centimetre, which is what the factors are stated in
    {
        'category': 'Length',
        'name': 'Centimeter',
        'symbol': 'cm',
        'factor': Decimal('1.0'),
        'is_reference': True,
        'rounding': Decimal('0.01'),
    },
    {
        'category': 'Length',
        'name': 'Meter',
        'symbol': 'm',
        'factor': Decimal('100.0'),
        'is_reference': False,
        'rounding': Decimal('0.01'),
    },
]


# US kitchen measures — food vertical, not the neutral base. A workspace in
# the neutral mode used to pick its default unit between pieces, kilograms
# and teacups. The food profile's seed adds these; installations that already
# have the rows keep them (``uoms`` has no owner column and is referenced by
# items, so nothing is deleted anywhere).
UOM_UNITS_US_KITCHEN: list[dict[str, Any]] = [
    {
        'category': 'Volume',
        'name': 'Fluid Ounce',
        'symbol': 'fl oz',
        'factor': Decimal('29.5735'),
        'is_reference': False,
        'rounding': Decimal('0.001'),
    },
    {
        'category': 'Volume',
        'name': 'Cup (US)',
        'symbol': 'cup',
        'factor': Decimal('236.588'),
        'is_reference': False,
        'rounding': Decimal('0.001'),
    },
    {
        'category': 'Volume',
        'name': 'Pint (US)',
        'symbol': 'pt',
        'factor': Decimal('473.176'),
        'is_reference': False,
        'rounding': Decimal('0.001'),
    },
    {
        'category': 'Volume',
        'name': 'Quart (US)',
        'symbol': 'qt',
        'factor': Decimal('946.353'),
        'is_reference': False,
        'rounding': Decimal('0.001'),
    },
    {
        'category': 'Volume',
        'name': 'Gallon (US)',
        'symbol': 'gal',
        'factor': Decimal('3785.41'),
        'is_reference': False,
        'rounding': Decimal('0.001'),
    },
]
