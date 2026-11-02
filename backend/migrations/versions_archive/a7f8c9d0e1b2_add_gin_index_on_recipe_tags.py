"""add GIN index on recipe tags JSON column

Improves performance of tag-based recipe filtering.

Revision ID: a7f8c9d0e1b2
Revises: b1d2e3f4a5c6
Create Date: 2026-03-31 00:00:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = 'a7f8c9d0e1b2'
down_revision = 'b1d2e3f4a5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        'ALTER TABLE recipes ALTER COLUMN tags TYPE JSONB USING tags::jsonb'
    )
    op.execute(
        'CREATE INDEX ix_recipes_tags_gin ON recipes USING GIN (tags jsonb_path_ops)'
    )


def downgrade() -> None:
    op.drop_index('ix_recipes_tags_gin', table_name='recipes')
    op.execute(
        'ALTER TABLE recipes ALTER COLUMN tags TYPE JSON USING tags::json'
    )
