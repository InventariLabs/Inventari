"""add document_line_id to stock_reservations

Revision ID: rsvdocline01
Revises: trgmidx01
Create Date: 2026-08-14

Backfills schema drift: databases that applied a1b2c3d4e5f6 (001
add_stock_reservations) before 042f5ca7 grew the document_line_id column
never received it, so every StockReservation query fails with
UndefinedColumnError (e.g. completing a document returns 500).
Conditional on purpose — fresh installs already get the column from the
current 001, so this must be a no-op there.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'rsvdocline01'
down_revision = 'trgmidx01'
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text('SELECT to_regclass(:t)'), {'t': f'public.{table_name}'}
        ).scalar()
    )


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text(
                'SELECT 1 FROM information_schema.columns '
                'WHERE table_schema = :s AND table_name = :t AND column_name = :c'
            ),
            {'s': 'public', 't': table_name, 'c': column_name},
        ).scalar()
    )


def _fk_exists(table_name: str, fk_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text(
                'SELECT 1 FROM information_schema.table_constraints '
                'WHERE table_schema = :s AND table_name = :t '
                'AND constraint_name = :c AND constraint_type = :ct'
            ),
            {
                's': 'public',
                't': table_name,
                'c': fk_name,
                'ct': 'FOREIGN KEY',
            },
        ).scalar()
    )


def upgrade() -> None:
    if _column_exists('stock_reservations', 'document_line_id'):
        return
    op.add_column(
        'stock_reservations',
        sa.Column('document_line_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    # document_lines is owned by the documents module migration — only add
    # the FK when the target table is there (module may be absent).
    if _table_exists('document_lines'):
        op.create_foreign_key(
            'stock_reservations_document_line_id_fkey',
            'stock_reservations',
            'document_lines',
            ['document_line_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    if not _column_exists('stock_reservations', 'document_line_id'):
        return
    if _fk_exists('stock_reservations', 'stock_reservations_document_line_id_fkey'):
        op.drop_constraint(
            'stock_reservations_document_line_id_fkey',
            'stock_reservations',
            type_='foreignkey',
        )
    op.drop_column('stock_reservations', 'document_line_id')
