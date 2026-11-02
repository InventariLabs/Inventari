"""shopping_lists module baseline — create shopping_lists tables.

Initial migration for the shopping_lists module, extracted from core baseline_001
as part of the module migration isolation effort.

These tables were previously created by:
- ``baseline_001_full_schema.py``: shopping_lists, shopping_list_items
- ``e4f5a6b7c8d9``: shopping_list_history
- ``d1e2f3a4b5c6``: added status, completed_at, archived_at columns to shopping_lists

This migration reflects the FINAL state (all columns from d1e2f3a4b5c6 included).

Tables:
- shopping_lists (incl. status/completed_at/archived_at from d1e2f3a4b5c6)
- shopping_list_items
- shopping_list_history (from e4f5a6b7c8d9)

``shopping_list_history`` keeps an explicit ``relation_exists`` guard around its
whole block: the core migration ``e4f5a6b7c8d9`` still pre-creates it, with its
indexes, on fresh installs where the core chain runs before module migrations.

Revision ID: 001_initial
Revises: None
Create Date: 2026-06-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_helpers import (
    create_index_if_absent,
    create_table_if_absent,
    relation_exists,
)
from sqlalchemy.dialects import postgresql

revision: str = '001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ('shopping_lists',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_table_if_absent(
        'shopping_lists',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('archived_at', sa.DateTime(timezone=True)),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    # The is_active index belongs to a column 006 drops, and this baseline
    # must re-run against a schema that no longer has it. A fresh chain
    # creates the column here and drops both a few revisions later, so the
    # index would only ever exist to be dropped.
    create_index_if_absent('ix_shopping_lists_status', 'shopping_lists', ['status'])

    create_table_if_absent(
        'shopping_list_items',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'shopping_list_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('shopping_lists.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'item_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('items.id', ondelete='SET NULL'),
        ),
        sa.Column(
            'category_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('categories.id'),
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column(
            'uom_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('uoms.id'),
        ),
        sa.Column('notes', sa.Text()),
        sa.Column('estimated_price', sa.Numeric(10, 2)),
        sa.Column('is_purchased', sa.Boolean(), nullable=False),
        sa.Column('purchased_at', sa.DateTime(timezone=True)),
        sa.Column(
            'purchased_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
        ),
        sa.Column('source', sa.String(50), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    create_index_if_absent(
        'ix_shopping_list_items_is_purchased',
        'shopping_list_items',
        ['is_purchased'],
    )

    # Core migration e4f5a6b7c8d9 pre-creates shopping_list_history on fresh
    # installs (the core chain runs fully before module migrations), including
    # the ix_* indexes below. Skip the whole block when the table exists.
    if not relation_exists('shopping_list_history'):
        create_table_if_absent(
            'shopping_list_history',
            sa.Column(
                'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
            ),
            sa.Column(
                'organization_id',
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                nullable=False,
            ),
            sa.Column(
                'original_list_id', postgresql.UUID(as_uuid=True), nullable=False
            ),
            sa.Column('original_list_name', sa.String(255), nullable=False),
            sa.Column('item_name', sa.String(255), nullable=False),
            sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('estimated_price', sa.Numeric(10, 2)),
            sa.Column('purchased_at', sa.DateTime(timezone=True)),
            sa.Column(
                'purchased_by',
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey('users.id'),
            ),
            sa.Column(
                'archived_at',
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        create_index_if_absent(
            'ix_shopping_list_history_organization_id',
            'shopping_list_history',
            ['organization_id'],
        )
        create_index_if_absent(
            'ix_shopping_list_history_original_list_id',
            'shopping_list_history',
            ['original_list_id'],
        )


def downgrade() -> None:
    op.drop_index(
        'ix_shopping_list_history_original_list_id',
        table_name='shopping_list_history',
    )
    op.drop_index(
        'ix_shopping_list_history_organization_id',
        table_name='shopping_list_history',
    )
    op.drop_table('shopping_list_history')

    op.drop_index(
        'ix_shopping_list_items_is_purchased', table_name='shopping_list_items'
    )
    op.drop_table('shopping_list_items')

    op.drop_index('ix_shopping_lists_status', table_name='shopping_lists')
    op.drop_table('shopping_lists')
