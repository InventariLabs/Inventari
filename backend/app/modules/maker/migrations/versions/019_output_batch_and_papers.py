"""maker module — a run files its output under a dated batch, and keeps its papers.

* ``maker_shelf_lives`` — how many days a product keeps, one row per
  organization and product: the best-before a run puts on its batch is the
  run's day plus this. Kept here rather than on ``product_templates`` for the
  reason the typed prices are: a product can be a catalogue row shared by
  every organization, and its shelf life is the maker's own fact.
* ``maker_production_orders.output_lot_id`` — the batch the run's output went
  into. Runs that named a batch before this revision find it by its name.
* ``maker_production_attachments`` — the photos and files filed under a run.

Revision ID: 019_output_batch_and_papers
Revises: 018_backfill_process_steps
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '019_output_batch_and_papers'
down_revision: str | None = '018_backfill_process_steps'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'maker_shelf_lives',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('product_template_id', sa.Uuid(), nullable=False),
        sa.Column('shelf_life_days', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('shelf_life_days > 0', name='ck_maker_shelf_life_positive'),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['product_template_id'], ['product_templates.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'organization_id',
            'product_template_id',
            name='uq_maker_shelf_life_org_template',
        ),
    )
    op.add_column(
        'maker_production_orders',
        sa.Column(
            'output_lot_id',
            sa.Uuid(),
            sa.ForeignKey('stock_lots.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    # A run that named its batch before the column existed opened that batch
    # by name on its product; the name finds it again.
    op.execute(
        """
        UPDATE maker_production_orders AS o
           SET output_lot_id = l.id
          FROM stock_lots AS l
         WHERE o.output_lot_name IS NOT NULL
           AND o.status IN ('COMPLETED', 'REVERSED')
           AND l.organization_id = o.organization_id
           AND l.product_template_id = o.output_template_id
           AND l.name = o.output_lot_name
        """
    )
    op.create_table(
        'maker_production_attachments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('production_order_id', sa.Uuid(), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('original_name', sa.String(255), nullable=False),
        sa.Column('content_type', sa.String(100), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('uploaded_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['production_order_id'],
            ['maker_production_orders.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_maker_attachment_order',
        'maker_production_attachments',
        ['organization_id', 'production_order_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_maker_attachment_order', 'maker_production_attachments')
    op.drop_table('maker_production_attachments')
    op.drop_column('maker_production_orders', 'output_lot_id')
    op.drop_table('maker_shelf_lives')
