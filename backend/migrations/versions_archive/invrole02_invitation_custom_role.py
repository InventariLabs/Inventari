"""carry a custom role on the invitation code

Revision ID: invrole02
Revises: orgsttype01
Create Date: 2026-08-23

An invitation could only name one of the four built-in member levels, so an
organization that defined its own role (say, "Magazynier" with read/write on
inventory and nothing else) still had to wait for the arrival and switch them
by hand. ``role_id`` points at the org-scoped role the join assigns; the enum
``role`` stays as the base level the built-in guards read.

SET NULL on role deletion: the invitation then degrades to its enum level
instead of dangling.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'invrole02'
# 's orgsttype01 branched from invrole01 in parallel; rebased onto it so
# `alembic upgrade head` has a single head again.
down_revision = 'orgsttype01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'organization_invitations',
        sa.Column('role_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_organization_invitations_role_id',
        'organization_invitations',
        'roles',
        ['role_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_organization_invitations_role_id', 'organization_invitations', type_='foreignkey'
    )
    op.drop_column('organization_invitations', 'role_id')
