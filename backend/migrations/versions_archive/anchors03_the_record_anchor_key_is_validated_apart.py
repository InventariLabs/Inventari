"""validate fk_items_stock_anchor in a transaction of its own

Revision ID: anchors03
Revises: anchors02
Create Date: 2026-09-27

``anchors02`` added the records' foreign key to their group's anchor
``NOT VALID``, and validated it in the next statement. Both ran in one
transaction, so the ``SHARE ROW EXCLUSIVE`` the ``ADD CONSTRAINT`` took on
``items`` and ``stock_anchors`` was held while every record was checked:
writes to either table waited out the whole scan.

A revision of its own is not enough to separate them. Alembic runs a whole
``upgrade`` in one transaction here (``env.py`` does not ask for one per
migration), so ``anchors02`` and this revision would still share it. The
``autocommit_block`` commits what came before — the ``ADD`` and its lock
with it — and runs the validation outside, where it takes ``SHARE UPDATE
EXCLUSIVE`` on ``items``, a lock that lets reads and writes through while
it checks the rows.

Where the key is already valid (a database created from the models) this is
a no-op. A record in a group with no anchor fails it, naming the constraint;
``anchors02`` filled the anchors first, so that is a record written between
the two by code that took no lock.

``downgrade`` does nothing: Postgres cannot un-validate a constraint, and
the constraint itself belongs to ``anchors02``.
"""

from alembic import op

revision = 'anchors03'
down_revision = 'anchors02'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute('ALTER TABLE items VALIDATE CONSTRAINT fk_items_stock_anchor')


def downgrade() -> None:
    pass
