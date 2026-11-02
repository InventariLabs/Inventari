"""a role belongs to an organization

Revision ID: roleorg01
Revises: aicapcheck01
Create Date: 2026-08-27

``roles`` allowed a row with no organization, and three queries read such a
row as belonging to every one of them: the roles list, the permission check
and the roles a user holds all asked for ``organization_id = :org OR
organization_id IS NULL``. One row was therefore a grant in every
organization of the installation, to whoever it was assigned to.

Nothing creates such a row today — ``create_role_async`` always sets the
organization — but multi-tenancy is a premise here, not a detail, and a
premise enforced by every caller remembering to is not enforced. The column
says it now.

An archived RBAC migration seeded two of them ("Seed two system-wide roles").
They are deleted with their assignments rather than moved: on this installation
they carry a permission set from the day they were written, and an account that
holds one also holds the built-in level on ``User.role``, which is what decides
once the row is gone.
"""

import sqlalchemy as sa
from alembic import op

revision = 'roleorg01'
down_revision = 'aicapcheck01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            'DELETE FROM user_roles WHERE role_id IN '
            '(SELECT id FROM roles WHERE organization_id IS NULL)'
        )
    )
    op.execute(sa.text('DELETE FROM roles WHERE organization_id IS NULL'))
    op.alter_column('roles', 'organization_id', nullable=False)


def downgrade() -> None:
    # The rows are not coming back; the column simply allows them again.
    op.alter_column('roles', 'organization_id', nullable=True)
