"""add active assignment unique constraint

Revision ID: z_add_active_assignment_uc
Revises:
Create Date: 2026-05-19

"""
from alembic import op

revision = 'z_add_active_assignment_uc'
down_revision = 'd9eb49e0a845'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_eq_assignments_active_per_item
        ON equipment_assignments (item_id)
        WHERE checked_in_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS uq_eq_assignments_active_per_item
        """
    )
