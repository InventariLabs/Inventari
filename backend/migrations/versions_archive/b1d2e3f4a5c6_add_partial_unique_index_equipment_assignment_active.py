"""add partial unique index for active equipment assignment

Prevents a race condition where two concurrent checkout requests could
both pass the "no active assignment" check and create duplicate active
assignments for the same item. The unique index enforces the invariant
at the database level: at most one NULL checked_in_at per item.

Revision ID: b1d2e3f4a5c6
Revises: c6e963b22a7a
Create Date: 2026-01-01 00:00:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = 'b1d2e3f4a5c6'
down_revision = 'c6e963b22a7a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX uq_eq_assignment_active
        ON equipment_assignments (item_id)
        WHERE checked_in_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS uq_eq_assignment_active')
