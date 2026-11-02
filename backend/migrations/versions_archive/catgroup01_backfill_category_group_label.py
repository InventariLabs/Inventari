"""backfill categories.group_label from the legacy category_type

Revision ID: catgroup01
Revises: itemowner02
Create Date: 2026-08-25

``group_label`` is the grouping an organization controls; ``category_type``
is seed data the model has described as read-only since ``group_label``
arrived. The filter on the categories screen read ``group_label ??
category_type`` so that older rows kept their group — but the form only ever
knew about ``group_label``, so those rows showed an empty group field while
the screen went on filing them under one. The group was visible and could
not be renamed, moved or removed.

Copying the code rather than a name keeps the three seeded values going
through the existing translation map, so a Polish installation does not
start saying FRIDGE.
"""

from alembic import op

revision = 'catgroup01'
down_revision = 'itemowner02'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE categories
           SET group_label = category_type
         WHERE group_label IS NULL
           AND category_type IS NOT NULL
        """
    )


def downgrade() -> None:
    # Only the rows this migration filled: a group typed by hand and one
    # copied from the legacy column are indistinguishable afterwards, so the
    # legacy column is what says which is which.
    op.execute(
        """
        UPDATE categories
           SET group_label = NULL
         WHERE group_label = category_type
        """
    )
