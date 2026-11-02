"""The status and cycle-count vocabularies become text with a CHECK.

Revision ID: 014_enums_are_text
Revises: 013_a_count_names_its_adjustment
Create Date: 2026-10-22

Core stores every enumerated value as text and lets the application own the
vocabulary; these three columns were the exception, native PostgreSQL types
whose next label would need ``ALTER TYPE ... ADD VALUE`` — a statement that
cannot run inside the transaction a migration runs in — in every installation.
Each column becomes ``varchar(20)`` with a CHECK constraint over the same
labels, so a later label is an ordinary constraint swap. The stored labels are
the lowercase values the models already persist and are carried over as they
are.

Downgrade rebuilds the native types and puts the columns back on them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = '014_enums_are_text'
down_revision: str | None = '013_a_count_names_its_adjustment'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (table, column, former native type, labels).
_COLUMNS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        'stock_takes',
        'status',
        'stocktakestatus',
        ('draft', 'in_progress', 'completed', 'cancelled'),
    ),
    (
        'cycle_count_schedules',
        'frequency',
        'cyclecountfrequency',
        ('daily', 'weekly', 'monthly', 'quarterly'),
    ),
    (
        'cycle_count_schedules',
        'scope',
        'cyclecountscope',
        ('all', 'zone', 'category'),
    ),
)


def _in_list(labels: tuple[str, ...]) -> str:
    return ', '.join(f"'{label}'" for label in labels)


def upgrade() -> None:
    for table, column, type_name, labels in _COLUMNS:
        constraint = f'ck_{table}_{column}'
        op.execute(
            f'ALTER TABLE {table} ALTER COLUMN {column} '
            f'TYPE varchar(20) USING {column}::text'
        )
        op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}')
        op.execute(
            f'ALTER TABLE {table} ADD CONSTRAINT {constraint} '
            f'CHECK ({column} IN ({_in_list(labels)}))'
        )
        op.execute(f'DROP TYPE IF EXISTS {type_name}')


def downgrade() -> None:
    for table, column, type_name, labels in _COLUMNS:
        constraint = f'ck_{table}_{column}'
        op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}')
        op.execute(f'CREATE TYPE {type_name} AS ENUM ({_in_list(labels)})')
        op.execute(
            f'ALTER TABLE {table} ALTER COLUMN {column} '
            f'TYPE {type_name} USING {column}::{type_name}'
        )
