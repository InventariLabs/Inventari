"""backfill items.module_name from the namespaces already on record

Revision ID: itemowner02
Revises: itemowner01
Create Date: 2026-08-25

A module writes its data under a ``meta_data`` namespace named after itself,
so the records that predate the column already say who they belong to. Named
here rather than read from the module registry: a migration records what was
true when it ran, and a registry that gains a module later must not change
what this one did.
"""

from alembic import op

revision = 'itemowner02'
down_revision = 'itemowner01'
branch_labels = None
depends_on = None

# The vertical modules that claimed their own records at the time of writing.
CLAIMED_MODULES = ('equipment',)


def upgrade() -> None:
    for module in CLAIMED_MODULES:
        op.execute(
            f"""
            UPDATE items
               SET module_name = '{module}'
             WHERE module_name IS NULL
               AND meta_data ? '{module}'
            """  # noqa: S608 - module names are literals in this file
        )
        # Records filed under one of the module's categories but saved
        # without its namespace — the import path wrote one, the form the
        # other.
        op.execute(
            f"""
            UPDATE items
               SET module_name = '{module}'
              FROM categories
             WHERE items.category_id = categories.id
               AND items.module_name IS NULL
               AND categories.context_tag = '{module}'
            """  # noqa: S608
        )


def downgrade() -> None:
    op.execute('UPDATE items SET module_name = NULL')
