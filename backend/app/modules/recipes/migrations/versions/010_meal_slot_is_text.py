"""The meal slot becomes text with a CHECK.

Revision ID: 010_meal_slot_is_text
Revises: 009_timestamps_carry_their_zone
Create Date: 2026-10-22

Core stores every enumerated value as text and lets the application own the
vocabulary; ``meal_plan_entries.slot`` was a native PostgreSQL ``mealslot``
type, whose next label would need ``ALTER TYPE ... ADD VALUE`` — a statement
that cannot run inside the transaction a migration runs in — in every
installation. The column becomes ``varchar(20)`` with a CHECK constraint over
the same labels. The stored labels stay uppercase, as the API has always sent
them.

Downgrade rebuilds the native type and puts the column back on it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = '010_meal_slot_is_text'
down_revision: str | None = '009_timestamps_carry_their_zone'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LABELS = "'LUNCH', 'BREAKFAST', 'DINNER', 'SNACK'"


def upgrade() -> None:
    op.execute(
        'ALTER TABLE meal_plan_entries ALTER COLUMN slot '
        'TYPE varchar(20) USING slot::text'
    )
    op.execute(
        'ALTER TABLE meal_plan_entries DROP CONSTRAINT IF EXISTS ck_meal_plan_entries_slot'
    )
    op.execute(
        'ALTER TABLE meal_plan_entries ADD CONSTRAINT ck_meal_plan_entries_slot '
        f'CHECK (slot IN ({_LABELS}))'
    )
    op.execute('DROP TYPE IF EXISTS mealslot')


def downgrade() -> None:
    op.execute(
        'ALTER TABLE meal_plan_entries DROP CONSTRAINT IF EXISTS ck_meal_plan_entries_slot'
    )
    op.execute(f'CREATE TYPE mealslot AS ENUM ({_LABELS})')
    op.execute(
        'ALTER TABLE meal_plan_entries ALTER COLUMN slot '
        'TYPE mealslot USING slot::mealslot'
    )
