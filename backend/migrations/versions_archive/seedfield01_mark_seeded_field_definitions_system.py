"""mark profile-seeded field definitions as system fields

Revision ID: seedfield01
Revises: stypei18n01
Create Date: 2026-09-21

Old organizations were seeded before the profile's field definitions carried
``is_system``. The flag is what the field renderer keys on: a system field's
label is the platform's catalogue entry (``items:fields.<key>``) and reads in
the reader's language; a field without it shows the raw label the seed wrote —
English forever, on every screen. A fresh onboarding marks these fields, so
only the organizations seeded earlier are locked out of their own catalogue.

This replays the marking the seed performed then, from a copy of the seed's
data frozen in this file (a revision imports no application code: the seed
lists are free to change, the chain is not). Matched by category code and
field key, and only where the seed itself claimed the flag: a field an
organization invented, whatever its name, keeps its flag and its own words.

One direction only: afterwards a marked field and a field the seed marked on
create are indistinguishable, so ``downgrade`` is a documented no-op (same
contract as ``uompcs01``).
"""

import json

import sqlalchemy as sa
from alembic import op

revision = 'seedfield01'
down_revision = 'stypei18n01'
branch_labels = None
depends_on = None

# code -> the keys the seed shipped as system fields for that category. Only the
# categories with at least one are listed; every other code has nothing to mark.
_SEEDED_SYSTEM_KEYS: dict[str, set[str]] = {
    'pork': {'cut_type', 'freeze_date'},
    'beef': {'cut_type', 'freeze_date'},
    'poultry': {'freeze_date'},
    'fish': {'freeze_date'},
    'seafood': {'freeze_date'},
    'dairy': {'lactose_free'},
    'cheese': {'lactose_free'},
    'drinks': {'abv'},
    'fresh_meat': {'cut_type'},
}


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text('SELECT id, code, field_definitions FROM categories')
    ).fetchall()
    for cat_id, code, definitions in rows:
        seeded_keys = _SEEDED_SYSTEM_KEYS.get(code)
        if not seeded_keys or not definitions:
            continue
        changed = False
        for definition in definitions:
            if not definition.get('is_system') and definition.get('key') in seeded_keys:
                definition['is_system'] = True
                changed = True
        if changed:
            conn.execute(
                sa.text(
                    'UPDATE categories '
                    'SET field_definitions = CAST(:defs AS json) '
                    'WHERE id = :id'
                ),
                {'defs': json.dumps(definitions), 'id': cat_id},
            )


def downgrade() -> None:
    # Nothing to un-mark: the flag cannot be attributed to this migration
    # afterwards, and stripping it would put the English labels back. Same
    # documented no-op as the other data backfills.
    pass
