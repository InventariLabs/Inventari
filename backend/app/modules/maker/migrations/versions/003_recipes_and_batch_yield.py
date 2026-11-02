"""maker module — add maker_recipes, rename qty_per_unit→qty_per_batch, backfill.

Creates the ``maker_recipes`` and ``maker_recipe_cost_lines`` tables, adds
``recipe_id`` / ``qty_per_batch`` / ``uom_id`` to ``maker_bom_lines`` (with
data backfill from existing rows), and adds ``recipe_id`` / ``actual_qty`` /
``overproduced`` / ``scrap_qty`` to ``maker_production_orders``.

Backfill summary:
  1. One ``maker_recipes`` row per distinct ``parent_template_id`` (yield=1,
     is_default=True, name from product_templates).
  2. ``maker_bom_lines.recipe_id`` set from the recipe matching
     ``parent_template_id``.
  3. ``maker_bom_lines.qty_per_batch`` copied from ``qty_per_unit``.
  4. ``maker_bom_lines.uom_id`` resolved by matching ``unit`` → ``uoms.symbol``
     (system uoms only; unmatched → NULL).
  5. ``maker_production_orders.recipe_id`` set from the default recipe matching
     ``output_template_id``.

Revision ID: 003_recipes_batch_yield
Revises: 002_cancel_reason_produced_item
Create Date: 2026-07-18
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

logger = logging.getLogger(__name__)

revision: str = '003_recipes_batch_yield'
down_revision: str | None = '002_cancel_reason_produced_item'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # -- 1. Create maker_recipes -------------------------------------------
    op.create_table(
        'maker_recipes',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'output_template_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column(
            'batch_yield_qty', sa.Numeric(12, 4), nullable=False, server_default='1'
        ),
        sa.Column(
            'batch_yield_uom_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('uoms.id'),
            nullable=True,
        ),
        sa.Column('process_steps', JSONB, nullable=True),
        sa.Column('reference_price', sa.Numeric(12, 2), nullable=True),
        sa.Column('is_default', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('source_recipe_id', sa.UUID(as_uuid=True), nullable=True),
        sa.Column('source_snapshot_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            'organization_id',
            'output_template_id',
            'name',
            name='uq_recipe_org_template_name',
        ),
    )
    op.create_index(
        'ix_recipe_org_template',
        'maker_recipes',
        ['organization_id', 'output_template_id'],
    )

    # Partial unique index: at most one default recipe per (org, template).
    op.execute(
        'CREATE UNIQUE INDEX uq_recipe_default_per_template '
        'ON maker_recipes (organization_id, output_template_id) '
        'WHERE is_default = TRUE'
    )

    # -- 2. Create maker_recipe_cost_lines ---------------------------------
    op.create_table(
        'maker_recipe_cost_lines',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'recipe_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('maker_recipes.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'organization_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('label', sa.String(120), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('sort_order', sa.Integer, server_default='0'),
    )
    op.create_index('ix_recipe_cost_recipe', 'maker_recipe_cost_lines', ['recipe_id'])
    op.create_index(
        'ix_recipe_cost_org', 'maker_recipe_cost_lines', ['organization_id']
    )

    # -- 3. Add nullable new columns to maker_bom_lines --------------------
    op.add_column(
        'maker_bom_lines',
        sa.Column('recipe_id', sa.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        'maker_bom_lines',
        sa.Column('qty_per_batch', sa.Numeric(12, 4), nullable=True),
    )
    op.add_column(
        'maker_bom_lines',
        sa.Column('uom_id', sa.UUID(as_uuid=True), nullable=True),
    )

    # -- 4. Add nullable new columns to maker_production_orders ------------
    op.add_column(
        'maker_production_orders',
        sa.Column('recipe_id', sa.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        'maker_production_orders',
        sa.Column('actual_qty', sa.Numeric(12, 3), nullable=True),
    )
    op.add_column(
        'maker_production_orders',
        sa.Column('overproduced', sa.Boolean, nullable=False, server_default='false'),
    )
    op.add_column(
        'maker_production_orders',
        sa.Column('scrap_qty', sa.Numeric(12, 3), nullable=True),
    )

    # -- 5. Backfill: create recipes from existing BOM lines ---------------
    bind = op.get_bind()

    # 5a. One recipe per distinct (org, parent_template_id).
    bind.execute(
        sa.text("""
        INSERT INTO maker_recipes
            (id, organization_id, output_template_id, name,
             batch_yield_qty, is_default, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            bl.organization_id,
            bl.parent_template_id,
            COALESCE(pt.name, 'Unnamed'),
            1,
            TRUE,
            NOW(),
            NOW()
        FROM (
            SELECT DISTINCT organization_id, parent_template_id
            FROM maker_bom_lines
        ) bl
        LEFT JOIN product_templates pt ON pt.id = bl.parent_template_id
    """)
    )

    # 5b. Set bom_lines.recipe_id from matching recipe.
    bind.execute(
        sa.text("""
        UPDATE maker_bom_lines AS bl
        SET recipe_id = r.id
        FROM maker_recipes AS r
        WHERE bl.organization_id = r.organization_id
          AND bl.parent_template_id = r.output_template_id
          AND r.is_default = TRUE
    """)
    )

    # 5c. Copy qty_per_unit → qty_per_batch.
    bind.execute(
        sa.text("""
        UPDATE maker_bom_lines SET qty_per_batch = qty_per_unit
    """)
    )

    # 5d. Resolve uom_id from system uoms by symbol match (unmatched → NULL + log).
    bind.execute(
        sa.text("""
        UPDATE maker_bom_lines AS bl
        SET uom_id = u.id
        FROM uoms AS u
        WHERE u.organization_id IS NULL
          AND u.symbol = bl.unit
    """)
    )
    unmatched_units = (
        bind.execute(
            sa.text("""
        SELECT DISTINCT bl.unit
        FROM maker_bom_lines AS bl
        WHERE NOT EXISTS (
            SELECT 1
            FROM uoms AS u
            WHERE u.organization_id IS NULL
              AND u.symbol = bl.unit
        )
    """)
        )
        .scalars()
        .all()
    )
    for unit in unmatched_units:
        logger.warning(
            'maker_bom_lines: no system uom matches unit %r — uom_id left NULL',
            unit,
        )

    # 5e. Set production_orders.recipe_id from matching default recipe.
    bind.execute(
        sa.text("""
        UPDATE maker_production_orders AS po
        SET recipe_id = r.id
        FROM maker_recipes AS r
        WHERE po.organization_id = r.organization_id
          AND po.output_template_id = r.output_template_id
          AND r.is_default = TRUE
    """)
    )

    # -- 6. Make new columns NOT NULL (after backfill) ---------------------
    op.alter_column('maker_bom_lines', 'recipe_id', nullable=False)
    op.alter_column('maker_bom_lines', 'qty_per_batch', nullable=False)

    # -- 7. Drop old constraints + column, add new constraints -------------
    op.drop_constraint('uq_bom_parent_child', 'maker_bom_lines', type_='unique')
    op.drop_constraint('ck_bom_qty_positive', 'maker_bom_lines', type_='check')

    op.drop_column('maker_bom_lines', 'qty_per_unit')

    op.create_unique_constraint(
        'uq_bom_recipe_child',
        'maker_bom_lines',
        ['recipe_id', 'child_template_id'],
    )
    op.create_check_constraint(
        'ck_bom_qty',
        'maker_bom_lines',
        'qty_per_batch > 0',
    )
    op.create_index('ix_bom_recipe', 'maker_bom_lines', ['recipe_id'])


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    # Reverse constraint / column changes on maker_bom_lines.
    op.drop_index('ix_bom_recipe', table_name='maker_bom_lines')
    op.drop_constraint('ck_bom_qty', 'maker_bom_lines', type_='check')
    op.drop_constraint('uq_bom_recipe_child', 'maker_bom_lines', type_='unique')

    # Restore qty_per_unit (nullable first, copy, then NOT NULL).
    op.add_column(
        'maker_bom_lines',
        sa.Column('qty_per_unit', sa.Numeric(12, 4), nullable=True),
    )
    op.execute(
        sa.text("""
        UPDATE maker_bom_lines SET qty_per_unit = qty_per_batch
    """)
    )
    op.alter_column('maker_bom_lines', 'qty_per_unit', nullable=False)

    op.create_check_constraint(
        'ck_bom_qty_positive',
        'maker_bom_lines',
        'qty_per_unit > 0',
    )
    op.create_unique_constraint(
        'uq_bom_parent_child',
        'maker_bom_lines',
        ['parent_template_id', 'child_template_id'],
    )

    # Drop new columns from maker_bom_lines.
    op.drop_column('maker_bom_lines', 'uom_id')
    op.drop_column('maker_bom_lines', 'qty_per_batch')
    op.drop_column('maker_bom_lines', 'recipe_id')

    # Drop new columns from maker_production_orders.
    op.drop_column('maker_production_orders', 'scrap_qty')
    op.drop_column('maker_production_orders', 'overproduced')
    op.drop_column('maker_production_orders', 'actual_qty')
    op.drop_column('maker_production_orders', 'recipe_id')

    # Drop maker_recipe_cost_lines.
    op.drop_index('ix_recipe_cost_org', table_name='maker_recipe_cost_lines')
    op.drop_index('ix_recipe_cost_recipe', table_name='maker_recipe_cost_lines')
    op.drop_table('maker_recipe_cost_lines')

    # Drop maker_recipes.
    op.execute('DROP INDEX IF EXISTS uq_recipe_default_per_template')
    op.drop_index('ix_recipe_org_template', table_name='maker_recipes')
    op.drop_table('maker_recipes')
