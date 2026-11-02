"""add stock_reservations table

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-06-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a1b2c3d4e5f6'
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text('SELECT to_regclass(:t)'), {'t': f'public.{table_name}'}
        ).scalar()
    )


def upgrade() -> None:
    # Create stock_reservations without the document_lines FK on fresh installs
    # (document_lines is now owned by the documents module migration).
    doc_line_fk = []
    if _table_exists('document_lines'):
        doc_line_fk = [
            sa.Column(
                'document_line_id',
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey('document_lines.id', ondelete='SET NULL'),
                nullable=True,
            )
        ]

    op.create_table(
        'stock_reservations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column(
            'document_id',
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        *doc_line_fk,
        sa.Column(
            'stock_quant_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('stock_quants.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column('quantity', sa.Numeric(12, 3), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # If document_lines exists but we created the table without inline FK
    # (module enabled later), add the column + FK now if missing.
    if not doc_line_fk and _table_exists('document_lines'):
        op.add_column(
            'stock_reservations',
            sa.Column('document_line_id', postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            'stock_reservations_document_line_id_fkey',
            'stock_reservations',
            'document_lines',
            ['document_line_id'],
            ['id'],
            ondelete='SET NULL',
        )

    op.create_index(
        'ix_reservation_org_doc',
        'stock_reservations',
        ['organization_id', 'document_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_reservation_org_doc', table_name='stock_reservations')
    op.drop_table('stock_reservations')
