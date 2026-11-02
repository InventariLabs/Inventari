"""every group of stock gets a row to lock: stock_anchors

Revision ID: anchors01
Revises: quantview01
Create Date: 2026-09-27

A change to stock locks the rows it is about to write before it reads what
is free. Those rows were quants — one per batch and owner — so the first
receipt to a shelf that had never held the product had nothing to lock, and
two of them at once were told apart only by the quant's unique key. The
quants also go away once the records are the only count.

``stock_anchors`` is one row per ``(organization, product, shelf)``, with no
quantity: the row a writer locks for the whole group, created by the lock
itself for a group that has none yet.

Filled here from every group a quant or a record names. A group whose
product, shelf or organization no longer exists is left out: an instance
that started from the first baseline carried no foreign keys and may still
hold such rows, and the anchor's own keys would refuse them.

``downgrade`` drops the table; no other table changes either way.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'anchors01'
down_revision = 'quantview01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'stock_anchors',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'product_template_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'storage_location_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'organization_id',
            'product_template_id',
            'storage_location_id',
            name='uq_stock_anchor_group',
        ),
    )
    op.create_index(
        'ix_stock_anchors_product_template_id', 'stock_anchors', ['product_template_id']
    )
    op.create_index(
        'ix_stock_anchors_storage_location_id', 'stock_anchors', ['storage_location_id']
    )
    op.execute(
        """
        INSERT INTO stock_anchors (id, organization_id, product_template_id, storage_location_id)
        SELECT gen_random_uuid(), groups.organization_id, groups.product_template_id,
               groups.storage_location_id
        FROM (
            SELECT organization_id, product_template_id, storage_location_id
            FROM stock_quants
            UNION
            SELECT organization_id, template_id, storage_location_id
            FROM items
            WHERE template_id IS NOT NULL AND storage_location_id IS NOT NULL
        ) AS groups
        JOIN organizations ON organizations.id = groups.organization_id
        JOIN product_templates ON product_templates.id = groups.product_template_id
        JOIN storage_locations ON storage_locations.id = groups.storage_location_id
        """
    )


def downgrade() -> None:
    op.drop_table('stock_anchors')
