"""printing module — a pool job answers for the labels it actually carries.

``read_permissions`` was decided from the kind of target a job named: every
pool job kept ``items:read`` and ``equipment:read``, so a role holding only
the register's read listed and resent a job carrying a product's label or one
nobody had assigned. New jobs take the reads of the labels they print (the
queue service trims the module reads none of them answers to). A job queued
before this revision is trimmed here from the labels it froze: a job with no
label assigned to an equipment record no longer carries ``equipment:read``.

Downgrade puts ``equipment:read`` back on every pool job, which is the rule
this revision replaced.

Revision ID: 008_pool_job_reads
Revises: 007_job_read_permission
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '008_pool_job_reads'
down_revision: str | None = '007_job_read_permission'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE print_jobs AS job
            SET read_permissions = (
                SELECT coalesce(jsonb_agg(permission), '[]'::jsonb)
                FROM jsonb_array_elements_text(job.read_permissions) AS permission
                WHERE permission <> 'equipment:read'
            )
            WHERE job.read_permissions @> '["equipment:read"]'::jsonb
              AND NOT EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(job.labels) AS entry
                  JOIN label_pool AS label
                    ON label.id = (entry ->> 'label_id')::uuid
                  JOIN items AS item ON item.id = label.item_id
                  JOIN categories AS category ON category.id = item.category_id
                  WHERE category.context_tag = 'equipment'
              )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE print_jobs
            SET read_permissions = read_permissions || '["equipment:read"]'::jsonb
            WHERE labels -> 0 ? 'label_id'
              AND NOT read_permissions @> '["equipment:read"]'::jsonb
            """
        )
    )
