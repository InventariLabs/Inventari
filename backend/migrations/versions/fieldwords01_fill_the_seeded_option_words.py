"""fill the option words of the fields seeded before the seed carried them

The seed of the Dairy and Cheese categories later learned ``options_i18n``, the
catalogue key of each option's word. The seed only inserts, so an organization
seeded earlier reads the field's label in its own language and the options as
the stored English: a Polish reader chooses between "No" and "Yes" under
"BEZ LAKTOZY".

That is the only part of the seeded field definitions this can happen to. The
seed's definitions gained two things after their first version, ``is_system``
and ``options_i18n``, and the previous chain already brought ``is_system`` to
every database it built. A module's declared fields are written again whenever
the module is enabled, so they need no backfill.

The words are copied here rather than imported: a revision imports no seed data,
which is free to change. Only a field still holding the seed's own options and
no words of its own is filled; anything an organization wrote keeps its words.
A later organization already has the map and sees no change.

``downgrade`` is a documented no-op: afterwards a filled field and a field the
seed wrote are indistinguishable, and emptying them would bring the English back.

Revision ID: fieldwords01
Revises: fknames01
Create Date: 2026-11-05
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'fieldwords01'
down_revision: str | None = 'fknames01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEEDED_CODES = ('dairy', 'cheese')
_SEEDED_KEY = 'lactose_free'
_SEEDED_OPTIONS = ['No', 'Yes']
_SEEDED_WORDS = {
    'No': 'items:fieldOptions.lactose_free.No',
    'Yes': 'items:fieldOptions.lactose_free.Yes',
}


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            'SELECT id, field_definitions FROM categories WHERE code = ANY(:codes)'
        ),
        {'codes': list(_SEEDED_CODES)},
    ).all()
    for category_id, definitions in rows:
        changed = False
        for definition in definitions or []:
            if (
                definition.get('key') == _SEEDED_KEY
                and definition.get('options') == _SEEDED_OPTIONS
                and not definition.get('options_i18n')
            ):
                definition['options_i18n'] = dict(_SEEDED_WORDS)
                changed = True
        if changed:
            conn.execute(
                sa.text(
                    'UPDATE categories SET field_definitions = CAST(:definitions AS json) '
                    'WHERE id = :id'
                ),
                {'definitions': json.dumps(definitions), 'id': category_id},
            )


def downgrade() -> None:
    # Nothing to undo: see the module docstring.
    pass
