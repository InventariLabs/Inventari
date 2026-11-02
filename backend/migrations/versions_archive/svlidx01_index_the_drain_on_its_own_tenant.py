"""index the drain on the organization that asks for it

Revision ID: svlidx01
Revises: svlasof01
Create Date: 2026-09-13

The FIFO drain reads one organization's open layers of one product
(``WHERE organization_id = ? AND product_template_id = ? AND remaining_qty > 0``)
on every receipt and every issue. ``ix_svl_template_remaining`` was ordered by
the template alone, and a template id is not unique across tenants: product
templates are shared, so every organization's cost history for the goods sits
under the same id. The index therefore found other organizations' layers and
the filter threw them away afterwards — rows read one by one on the hottest
path in the ledger, growing with every tenant that sells the same product.

The organization moves to the front, where the query's own filter is. The
columns beside it are unchanged, so the index still answers the template and
the ``remaining_qty`` cut, and ``ix_svl_org_template`` becomes a prefix of it;
that narrower index is deliberately left standing — retiring it is a decision
about a table written on every movement, and not one this change makes.

Built CONCURRENTLY inside an autocommit block, following the journal's and
the as-of valuation's index migrations: the ledger is written on every
receipt, pick and correction, and the non-concurrent form would hold a write
lock on it for the length of the build — meaning nobody could receive or
issue anything meanwhile. The concurrent form cannot run inside a
transaction, which is also why this migration has no repair helper: the drop
runs before the create, so if a build is interrupted the leftover index is
INVALID, and the drop of the next run removes it before the create tries
again. It is also why the drop names no validity check — the index is
replaced, not repaired.
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'svlidx01'
down_revision: str | None = 'svlasof01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = 'ix_svl_template_remaining'

#: The order the drain's filter asks in — the organization first, because a
#: template id alone spans every tenant.
_COLUMNS = 'organization_id, product_template_id, remaining_qty'
#: The shape this migration replaces, kept so the downgrade restores exactly
#: the index that was there.
_COLUMNS_BEFORE = 'product_template_id, remaining_qty'


def upgrade() -> None:
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}')
        conn.exec_driver_sql(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} '
            f'ON stock_valuation_layers ({_COLUMNS})'
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}')
        conn.exec_driver_sql(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} '
            f'ON stock_valuation_layers ({_COLUMNS_BEFORE})'
        )
