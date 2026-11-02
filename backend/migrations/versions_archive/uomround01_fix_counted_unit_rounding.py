"""give counted units a rounding of 1, and put the Length reference on the scale

Revision ID: uomround01
Revises: catgroup01
Create Date: 2026-08-25

Units were seeded by two lists that had drifted. The one a product profile
used carried no ``rounding`` at all, so its rows took the column default of
0.01 — a quantity in pieces could be recorded in hundredths of a piece.

The Length category is a smaller matter and a real one: its factors are
stated in centimetres, and ``is_reference`` sat on Meter. Conversion is a
ratio, so nothing computed wrongly; the catalogue simply described itself
incorrectly to anyone reading it. Moving the flag takes two statements
rather than one — ``uq_uom_category_reference`` allows a single reference
per category, and it is checked row by row, so the old flag has to be
cleared before the new one is set.

Only rows still holding the default rounding are touched. A rounding an
organization chose deliberately is not this migration's business.
"""

from alembic import op

revision = 'uomround01'
down_revision = 'catgroup01'
branch_labels = None
depends_on = None

COUNTED_UNITS = ('Piece', 'Pack', 'Can', 'Bottle', 'Box', 'Bag')

_CLEAR_LENGTH_REFERENCE = """
    UPDATE uoms
       SET is_reference = FALSE
      FROM uom_categories
     WHERE uoms.category_id = uom_categories.id
       AND uoms.is_system IS TRUE
       AND uoms.is_reference IS TRUE
       AND uom_categories.name = 'Length'
"""


def _set_length_reference(symbol: str) -> str:
    return f"""
        UPDATE uoms
           SET is_reference = TRUE
          FROM uom_categories
         WHERE uoms.category_id = uom_categories.id
           AND uoms.is_system IS TRUE
           AND uoms.symbol = '{symbol}'
           AND uom_categories.name = 'Length'
    """  # noqa: S608 - the symbol is a literal chosen by the caller below


def _set_counted_rounding(from_value: str, to_value: str) -> str:
    names = ', '.join(f"'{name}'" for name in COUNTED_UNITS)
    return f"""
        UPDATE uoms
           SET rounding = {to_value}
         WHERE is_system IS TRUE
           AND rounding = {from_value}
           AND name IN ({names})
    """  # noqa: S608 - unit names and both values are literals in this file


def upgrade() -> None:
    op.execute(_set_counted_rounding('0.01', '1.0'))
    op.execute(_CLEAR_LENGTH_REFERENCE)
    op.execute(_set_length_reference('cm'))


def downgrade() -> None:
    op.execute(_set_counted_rounding('1.0', '0.01'))
    op.execute(_CLEAR_LENGTH_REFERENCE)
    op.execute(_set_length_reference('m'))
