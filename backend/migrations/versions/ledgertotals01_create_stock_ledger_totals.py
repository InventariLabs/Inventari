"""create stock_ledger_totals - the ledger's net per product and shelf, kept by triggers

The stock reconciliation compared every shelf with what the movement ledger
nets to there, and added that up from the organization's whole ledger on every
pass, every six hours. The ledger is append-only, so the pass cost more each
time and never less. The net now lives in a table of its own, one row per
product and shelf, and the reconciliation reads that.

The table is moved by triggers on ``stock_moves``, in the statement that
writes the movement: no code path that writes a movement can forget it, and
there is no checkpoint to fall behind. The triggers are statement-level with
transition tables, so a posting that writes its movements in one statement
moves each total once, and they take the totals' rows in key order, so two
statements writing the same groups wait for each other rather than deadlock.
A removed movement only subtracts from a row that is still there: when a
cascade from the product, the shelf or the organization takes the movements,
it takes their totals too, and putting a row back would fail its foreign key.

``ledgertotals02`` fills the table from the movements already written.

Revision ID: ledgertotals01
Revises: listreads01
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'ledgertotals01'
down_revision: str | None = 'listreads01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The function and its three triggers. Kept verbatim: the test databases run
#: these same statements (``conftest.py``), so the suite is kept by what ships.
#: One trigger per event because a trigger with transition tables may have
#: only one.
TRIGGER_SQL = (
    r"""
    CREATE FUNCTION stock_ledger_totals_follow_moves() RETURNS trigger
    LANGUAGE plpgsql SET search_path = public AS $$
    BEGIN
        IF TG_OP IN ('INSERT', 'UPDATE') THEN
            INSERT INTO stock_ledger_totals AS t
                (organization_id, product_template_id, storage_location_id, quantity)
            SELECT organization_id, product_template_id, location_id, sum(qty)
            FROM (
                SELECT organization_id, product_template_id,
                       to_location_id AS location_id, quantity AS qty
                FROM new_moves
                WHERE state = 'done' AND to_location_id IS NOT NULL
                UNION ALL
                SELECT organization_id, product_template_id,
                       from_location_id, -quantity
                FROM new_moves
                WHERE state = 'done' AND from_location_id IS NOT NULL
            ) AS sides
            GROUP BY organization_id, product_template_id, location_id
            ORDER BY organization_id, product_template_id, location_id
            ON CONFLICT (organization_id, product_template_id, storage_location_id)
            DO UPDATE SET quantity = t.quantity + EXCLUDED.quantity;
        END IF;
        IF TG_OP IN ('UPDATE', 'DELETE') THEN
            UPDATE stock_ledger_totals AS t
            SET quantity = t.quantity - gone.qty
            FROM (
                SELECT organization_id, product_template_id, location_id,
                       sum(qty) AS qty
                FROM (
                    SELECT organization_id, product_template_id,
                           to_location_id AS location_id, quantity AS qty
                    FROM old_moves
                    WHERE state = 'done' AND to_location_id IS NOT NULL
                    UNION ALL
                    SELECT organization_id, product_template_id,
                           from_location_id, -quantity
                    FROM old_moves
                    WHERE state = 'done' AND from_location_id IS NOT NULL
                ) AS sides
                GROUP BY organization_id, product_template_id, location_id
            ) AS gone
            WHERE t.organization_id = gone.organization_id
              AND t.product_template_id = gone.product_template_id
              AND t.storage_location_id = gone.location_id;
        END IF;
        RETURN NULL;
    END
    $$
    """,
    """
    CREATE TRIGGER stock_ledger_totals_on_insert
        AFTER INSERT ON stock_moves
        REFERENCING NEW TABLE AS new_moves
        FOR EACH STATEMENT EXECUTE FUNCTION stock_ledger_totals_follow_moves()
    """,
    """
    CREATE TRIGGER stock_ledger_totals_on_update
        AFTER UPDATE ON stock_moves
        REFERENCING OLD TABLE AS old_moves NEW TABLE AS new_moves
        FOR EACH STATEMENT EXECUTE FUNCTION stock_ledger_totals_follow_moves()
    """,
    """
    CREATE TRIGGER stock_ledger_totals_on_delete
        AFTER DELETE ON stock_moves
        REFERENCING OLD TABLE AS old_moves
        FOR EACH STATEMENT EXECUTE FUNCTION stock_ledger_totals_follow_moves()
    """,
)


def upgrade() -> None:
    op.create_table(
        'stock_ledger_totals',
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('product_template_id', sa.Uuid(), nullable=False),
        sa.Column('storage_location_id', sa.Uuid(), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=18, scale=3), nullable=False),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['product_template_id'], ['product_templates.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['storage_location_id'], ['storage_locations.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint(
            'organization_id', 'product_template_id', 'storage_location_id'
        ),
    )
    op.create_index(
        op.f('ix_stock_ledger_totals_product_template_id'),
        'stock_ledger_totals',
        ['product_template_id'],
    )
    op.create_index(
        op.f('ix_stock_ledger_totals_storage_location_id'),
        'stock_ledger_totals',
        ['storage_location_id'],
    )
    for statement in TRIGGER_SQL:
        op.execute(statement)


def downgrade() -> None:
    for event in ('insert', 'update', 'delete'):
        op.execute(
            f'DROP TRIGGER IF EXISTS stock_ledger_totals_on_{event} ON stock_moves'
        )
    op.execute('DROP FUNCTION IF EXISTS stock_ledger_totals_follow_moves()')
    op.drop_index(
        op.f('ix_stock_ledger_totals_storage_location_id'),
        table_name='stock_ledger_totals',
    )
    op.drop_index(
        op.f('ix_stock_ledger_totals_product_template_id'),
        table_name='stock_ledger_totals',
    )
    op.drop_table('stock_ledger_totals')
